import asyncio
import ssl
import struct
import json
import time
import uuid
import base64
import os
import zlib
from datetime import datetime
from datetime import timezone as datetimezone
from urllib.parse import urlencode
import redis.asyncio as redis  # 使用异步 redis 库
from django.conf import settings

from django.core.management.base import BaseCommand
from channels.db import database_sync_to_async
from django.utils import timezone

from teemog1_api.models import WatchDevice, LocationPackage, LocationData, Contact, CallRecord, ChatLog, SmsMessage
from django.contrib.auth.models import User
from teemog1_api.NativeUtils import NativeUtils

import logging

logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

# --- 配置 ---
TCP_HOST = '0.0.0.0'
TCP_PORT = 59093
CERT_FILE = './ca.crt'  # 证书和私钥路径
KEY_FILE = './ca.key'
CLIENTS = {}


async def redis_listener():
    """监听 Redis 的 'contacts_notify' 频道"""
    r = redis.from_url("redis://localhost", decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("contacts_notify")  # 频道名可以更通用一些
    logger.info("[*] Redis 订阅器已启动，正在监听 'contacts_notify' 频道...")

    while True:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message['data']:

                # {'command': 'add_contact', 'udid': udid, 'contact_id': new_contact_user_id}
                data_str = message['data']
                data = json.loads(data_str)
                command = data.get('command')

                if command == 'add_contact':
                    udid = data['udid']
                    new_contact_user_id = data['contact_id']
                    logger.debug(f"[*] 从 Redis 收到通知：为设备 {udid} 添加联系人 {new_contact_user_id}。")

                    if udid in CLIENTS:
                        writer = CLIENTS[udid]
                        try:
                            device = await database_sync_to_async(WatchDevice.objects.get)(udid=udid)

                            # 调用新的推送包构造函数
                            response_packet = await handle_add_contact_push_db(device, int(new_contact_user_id))

                            if response_packet:
                                writer.write(response_packet)
                                await writer.drain()
                                logger.debug(f"[*] 已通过 TCP 连接向 {udid} 推送 'add' 联系人消息。")
                        except Exception as e:
                            logger.error(f"[!] 推送 'add' 联系人消息到 {udid} 时出错: {e}")
                    else:
                        logger.error(f"[!] 收到 'add' 通知，但设备 {udid} 当前未连接。")
        except Exception as e:
            logger.error(f"[!] Redis 监听器出错: {e}")
            await asyncio.sleep(5)


def parse_chat_message_packet(payload: bytes):
    """
    专门解析类型为 0x7a (聊天消息) 的载荷。
    载荷结构: [2-byte json_len][json_data][binary_data]
    """
    if len(payload) < 5:
        logger.error("[!] 聊天消息载荷过短，无法解析 JSON 长度。")
        return None, None

    try:
        length, version, msg_type = struct.unpack('>i', b'\x00' + payload[:3])[0], payload[3], payload[4]
        # logger.debug(f"[*] 解析TCP包: 声明长度=0x{length:02x}, 版本=0x{version:02x}, 类型=0x{msg_type:02x}")
        payload = payload[5:]
        # 解包前2个字节作为大端序的 unsigned short (H)
        json_len = struct.unpack('>H', payload[:2])[0]

        json_end = 2 + json_len
        if len(payload) < json_end:
            logger.error(f"[!] 聊天消息载荷不完整。声明的JSON长度为 {json_len}，但实际载荷只有 {len(payload)}。")
            return None, None

        json_bytes = payload[2:json_end]
        json_data = json.loads(json_bytes.decode('utf-8'))

        # 剩余部分是二进制数据 (如语音)
        binary_data = payload[json_end:]

        return json_data, binary_data

    except (struct.error, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[!] 解析聊天消息载荷失败: {e}")
        return None, None


def parse_teemo_zlib_packet(data):
    if len(data) < 7:
        return None, None
    length, version, msg_type = struct.unpack('>i', b'\x00' + data[:3])[0], data[3], data[4]
    # logger.debug(f"[*] 解析TCP包: 声明长度=0x{length:02x}, 版本=0x{version:02x}, 类型=0x{msg_type:02x}")
    payload_zlib = data[5:]
    try:
        payload = zlib.decompress(payload_zlib)
    except zlib.error as e:
        logger.error(f"[!] 解压payload失败: {e}\n    原始Payload: {payload}")
        return payload, None
    try:
        json_data = json.loads(payload.decode('utf-8'))
        return json_data, None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[!] 解析JSON失败: {e}\n    原始Payload: {payload}")
        return payload, None


def parse_teemo_packet(data):
    if len(data) < 5:
        return None, None
    length, version, msg_type = struct.unpack('>i', b'\x00' + data[:3])[0], data[3], data[4]
    # logger.debug(f"[*] 解析TCP包: 声明长度=0x{length:02x}, 版本=0x{version:02x}, 类型=0x{msg_type:02x}")
    payload = data[5:]
    try:
        json_data = json.loads(payload.decode('utf-8'))
        return json_data, None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error(f"[!] 解析JSON失败: {e}\n    原始Payload: {payload}")
        return payload, None


def create_teemo_response_packet(msg_type, json_payload):
    payload_bytes = json.dumps(json_payload).encode('utf-8')
    length = 2 + len(payload_bytes)
    version = 4
    header = struct.pack('>i', length)[1:] + bytes([version, msg_type])
    return header + payload_bytes


@database_sync_to_async
def handle_login_request_db(device_instance: WatchDevice | None, req_json_data: dict, **kwargs):
    """处理登录请求并与数据库交互"""
    valid = True
    udid = req_json_data.get('udid')
    if not udid or len(udid) < 16:
        logger.error(f"params udid invalid: {udid}")
        valid = False
    iccid = req_json_data.get('iccid')
    # if not iccid or len(iccid) < 16:
    #     logger.error(f"params iccid invalid: {iccid}")
    #     valid = False
    imei = req_json_data.get('imei')
    if not imei or len(imei) < 15:
        logger.error(f"params imei invalid: {imei}")
        valid = False
    imsi = req_json_data.get('imsi')
    # if not imsi or len(imsi) < 15:
    #     logger.error(f"params imsi invalid: {imsi}")
    #     valid = False
    mac = req_json_data.get('mac')
    if not mac or len(mac) < 17:
        logger.error(f"params mac invalid: {mac}")
        valid = False

    if not valid:
        return None, {"status": 0, "msg": "params invalid."}

    # 查找或创建设备
    device, created = WatchDevice.objects.get_or_create(
        udid=udid,
        defaults={
            'baby_id': int(time.time()),  # 用时间戳生成一个唯一的 baby_id
            'ssn': req_json_data.get('imei', ''),
            'iccid': iccid,
            'imei': imei,
            'imsi': imsi,
            'mac': mac
        }
    )

    # 每次登录都更新 token 和状态
    device.http_token = uuid.uuid4()
    # device.is_bound = True
    device.device_version = req_json_data.get('device_version')
    device.ssn = req_json_data.get('ssn', "")
    device.mac = req_json_data.get('mac', "")
    device.imei = req_json_data.get('imei', "")
    device.imsi = req_json_data.get('imsi', "")
    device.save()

    logger.info(f"[*] 设备 {'创建' if created else '找到'}: {device.udid}")

    response_payload = {
        # 身份认证相关
        # 状态，1:OK， 0: error, msg: 错误信息
        "status": 1,
        # 手表是否已经绑定， 1: 绑定, 0: 未绑定
        "binded": 1 if device.is_bound else 0,
        # 手表是否已经停用， 1: 停用, 0: 正常
        "halted": 1 if device.is_halted else 0,
        # 手表使用者的唯一ID
        "baby_id": device.baby_id,
        # 用于后续HTTP请求的身份验证令牌
        "http_token": str(device.http_token),

        # 服务器当前的Unix时间戳（秒），用于手表校准时间
        "stamp": int(time.time()),  # 提供当前时间戳
        # 消息文本。
        # 主要用于调试或在某些情况下向用户显示信息。当 status 为 0 时，这里会是错误详情。
        "msg": "login in successful.",
        # 用于绑定的二维码信息
        # 当 binded 为 0 时，手表会使用这两个字段来生成并显示二维码
        # 二维码的内容为qr_url+qr_code
        "qr_code": "" if device.is_bound else settings.TEEMOG1_QQ_CODE + f"?{urlencode({'u':udid, 'i': imei})}",
        "qr_url": "" if device.is_bound else settings.QQ_QR_URL,
        # 服务号码
        # SmsReceiver.java 中，手表可能会向这个号码发送包含加密后IMSI的短信
        "service_number": "10086",
        # TCP心跳间隔时间（秒）
        "pingpong": 300,
        # 各种资源（表情、联系人、主题、表盘等）的版本号
        # 如果服务器的版本号更高，手表就会发起请求去下载新资源
        "emoticon_ver": 1,
        "contact_ptt_ver": 1,
        "family_ptt_ver": 1,
        "friend_ptt_ver": 1,
        "theme_ver": "1",
        "dial_ver": "1",
        "cover_ver": "1",
        # 可能与SIM卡的流量、有效期等信息有关
        "current_month": 0,
        "current_remainder": 0,
        "expired": 0,
        "next_remainder": 0,
    }

    return device, create_teemo_response_packet(0x14, response_payload)


def handle_weather_request(device_instance: WatchDevice, req_json_data: dict, **kwargs):
    """
    处理天气请求 (类型 123,20)，并返回一个表示成功的响应包
    """
    if not device_instance or not isinstance(req_json_data, dict):
        return
    weather_response = {
        "status": 1,
        "msg": "",
        "sub_type": 20, "user_id": device_instance.udid,
        "data": {}
    }
    # if settings.ONLY_LOGIN:
    #     return create_teemo_response_packet(123, weather_response)
    logger.debug("[*] 检测到天气请求 (类型 123,20)，正在构造成功响应...")
    weather_response['data'] = {
        "info": {
            "aq": "优",
            "icon": "qing",
            "mositure": "",
            "pm25": 30,
            "temp_now": 25,
            "title": "今天天气不错！",
            "weather": "晴",
            "wind": "微风"
        },
        "forcast": [
            {
                "date": datetime.datetime.now().strftime("%m.%d"),  # 生成 "02.07"
                "icon": "qing",
                "temp_high": 28,
                "temp_low": 18,
            },
            {
                "date": (datetime.datetime.now()+datetime.timedelta(days=1)).strftime("%m.%d"),
                "icon": "duoyun",
                "temp_high": 29,
                "temp_low": 19,
            }
        ],
        "life": {
            "cy": "适宜",
            "cy_desc": "适合穿衣",
            "dl": "适宜",
            "dl_desc": "适合锻炼",
            "gm": "感冒",
            "gm_desc": "不易感冒",
            "zwx": "中等",
            "zwx_desc": "紫外线中等"
        }
    }
    response_packet = create_teemo_response_packet(123, weather_response)
    return response_packet


@database_sync_to_async
def handle_add_contact_push_db(device_instance: WatchDevice, new_contact_user_id):
    """
    为单个新增联系人构造一个 "type": "add" 的推送包。
    """
    if settings.ONLY_LOGIN:
        return None
    try:
        contact = Contact.objects.get(device=device_instance, user_id=new_contact_user_id)
    except Contact.DoesNotExist:
        logger.error(f"[!] 无法构造推送包：在数据库中找不到新增的联系人 ID {new_contact_user_id}")
        return None

    logger.debug(f"[*] 正在为新增联系人 '{contact.name}' 构造 'add' 类型的推送包...")

    contact_data = {
        "user_id": contact.user_id,
        "name": contact.name,
        "phone": contact.phone,
        "photo": contact.photo or "",
        "contacts_type": contact.contacts_type,
        "admin": contact.admin,
        "spell": contact.spell or "",
        "device_type": 100 if contact.admin == 1 else 2,
        "auth": contact.auth,
        "ext": contact.get_ext_phones()
    }

    # 根据联系人类型，决定放入哪个分组
    contacts_down_data = {}
    current_version = int(time.time())

    if contact.contacts_type == Contact.ContactType.FAMILY:
        contacts_down_data["family_users"] = {
            "to_version": current_version,
            "data": [{"type": "add", "person": [contact_data]}]  # <-- 关键: type 为 "add"
        }
    elif contact.contacts_type == Contact.ContactType.FRIEND:
        contacts_down_data["friends"] = {
            "to_version": current_version,
            "data": [{"type": "add", "person": [contact_data]}]
        }
    else:  # 默认为普通联系人
        contacts_down_data["contacts"] = {
            "to_version": current_version,
            "data": [{"type": "add", "person": [contact_data]}]
        }

    final_response = {
        "sub_type": 2,  # 子类型依然是联系人同步
        "data": contacts_down_data
    }

    logger.debug("[*] 'add' 类型联系人推送包已生成。")
    return create_teemo_response_packet(123, final_response)


@database_sync_to_async
def handle_contact_request_db(device_instance: WatchDevice, req_json_data: dict, **kwargs):
    """
    处理联系人同步请求，从数据库查询并构造响应包。
    接收一个 WatchDevice 实例作为参数。
    """
    if settings.ONLY_LOGIN:
        return None
    if not device_instance or not isinstance(req_json_data, dict):
        return
    logger.debug("[*] 检测到联系人请求 (类型 123,2)，正在构造成功响应...")

    logger.debug(f"[*] 为设备 {device_instance.udid} 查询联系人...")

    # 从数据库中获取该设备的所有联系人
    all_contacts = Contact.objects.filter(device=device_instance).order_by('spell', 'name')

    # 按类型分组
    family_list = []
    friend_list = []
    contact_list = []

    for contact in all_contacts:
        contact_data = {
            "user_id": contact.user_id,
            "name": contact.name,
            "phone": contact.phone,
            "photo": contact.photo or "",  # 确保 photo 字段不是 None
            "contacts_type": contact.contacts_type,
            "admin": contact.admin,
            "spell": contact.spell or "",
            "device_type": 100 if contact.admin == 1 else 2,
            "auth": contact.auth,
            "ext": contact.get_ext_phones()  # 使用辅助方法获取列表
        }

        if contact.contacts_type == Contact.ContactType.FAMILY:
            family_list.append(contact_data)
        elif contact.contacts_type == Contact.ContactType.FRIEND:
            friend_list.append(contact_data)
        elif contact.contacts_type == Contact.ContactType.NORMAL:
            contact_list.append(contact_data)

    current_version = int(time.time())

    # 构造家人分组的 Profile 信息 (可以考虑也存到数据库中)
    family_profile = {
        "family_id": device_instance.baby_id,  # 使用 baby_id 作为 family_id
        "family_name": "我的家",
        "family_photo": "", "portrait": 0, "spell": "WODEJIA"
    }

    contacts_down_data = {
        "family_users": {
            "to_version": current_version,
            "profile": family_profile,
            "data": [{"type": "all", "person": family_list}]
        },
        "friends": {
            "to_version": current_version,
            "profile": None,  # 或者一个空对象 {}，None 在 json.dumps 后会变成 null
            "data": [{"type": "all", "person": friend_list}]
        },
        "contacts": {
            "to_version": current_version,
            "profile": None,
            "data": [{"type": "all", "person": contact_list}]
        }
    }

    final_response = {
        "status": 1,
        "msg": "",
        "sub_type": 2,
        "data": contacts_down_data
    }

    logger.debug(f"[*] 为设备 {device_instance.udid} 生成了包含 {len(all_contacts)} 个联系人的响应包。")
    logger.debug(json.dumps(final_response, indent=2, ensure_ascii=False))  # 日志太长，可以注释掉

    return create_teemo_response_packet(123, final_response)


@database_sync_to_async
def handle_sms_record_db(device_instance: WatchDevice, sms_data: dict, **kwargs):
    """
    处理短信上报，并将其存入数据库
    """
    if settings.ONLY_LOGIN:
        return None
    if not device_instance:
        return None
    sms_log = SmsMessage.objects.create(
        device=device_instance,                # 必须填入关联的 WatchDevice 实例
        message=sms_data.get('message', ''),       # 获取短信内容
        phone=sms_data.get('phone', ''),           # 获取电话号码
        error_cause=int(sms_data.get('error_cause', '0')),
        stamp=timezone.now()                 # 生成当前时间戳（秒级），如果需要毫秒则 *1000
    )
    return
    # 清空所有短信
    # return create_teemo_response_packet(28, {"status": 1, "msg": ""})
    # 给指定号码发短信
    # return create_teemo_response_packet(57, {"phone": 10086, "msg": "abc"})
    # 给service_number发imsi_xxx
    # return create_teemo_response_packet(57, {"service_number": 10086, "msg": ""})


@database_sync_to_async
def handle_call_record_db(device_instance: WatchDevice, record_data: dict, **kwargs):
    """
    处理通话记录上报，并将其存入数据库
    """
    if settings.ONLY_LOGIN:
        return None
    if not device_instance or 'recents' not in record_data:
        return None

    saved_records = []
    for record in record_data.get('recents', []):
        record_id = record.get('id')
        if not record_id:
            continue

        # 使用 update_or_create 避免重复创建
        # 我们使用 record_id 作为唯一标识
        obj, created = CallRecord.objects.update_or_create(
            record_id=record_id,
            defaults={
                'device': device_instance,
                'phone_number': record.get('phone'),
                'name': record.get('name'),
                'call_type': record.get('in', 0),
                # 手表上报的是秒级时间戳，转换为 Django 的 DateTimeField
                'stamp': datetime.fromtimestamp(record.get('stamp', 0), tz=datetimezone.utc),
                'duration': record.get('time', 0),
                'geo_data_json': json.dumps(record.get('geo_data')),
                'is_read': record.get('is_read') == 1,
                'is_sync': True,  # 既然服务器收到了，就标记为已同步
            }
        )

        # 尝试将记录与现有联系人关联
        # 这是一个可选的优化，可以后台任务做
        try:
            contact = Contact.objects.filter(device=device_instance, phone=obj.phone_number).first()
            if contact:
                obj.contact = contact
                obj.save(update_fields=['contact'])
        except Exception:
            pass

        logger.info(f"[*] 通话记录 {'创建' if created else '更新'}: ID {record_id} for device {device_instance.udid}")
        saved_records.append(record_id)

    # 根据源码 RecordRemoteDataSource，服务器需要回复一个确认包
    # 这个包的结构是 RecordDownData
    response_payload = {
        # 我们需要确认收到了哪个批次的记录，这里使用上报包的 id
        "id": record_data.get('id'),
        # 其他字段可以给默认值
        "current_month": 0,
        "current_remainder": 0,
        "next_remainder": 0
    }

    return create_teemo_response_packet(52, response_payload)


def handle_apps_request(device_instance: WatchDevice, req_json_data: dict, **kwargs):
    """
    处理APP列表 (类型 123,32)，并返回一个表示成功的响应包
    """
    if not device_instance or not isinstance(req_json_data, dict):
        return
    logger.debug("[*] 检测到APP列表消息 (类型 123,32)，正在构造成功响应...")
    contact_response = {
        "status": 1,
        "msg": "",
        "sub_type": 32
    }
    response_packet = create_teemo_response_packet(123, contact_response)
    return response_packet


@database_sync_to_async
def handle_location_msg(device_instance: WatchDevice, req_json_data: dict, **kwargs):
    """
    处理位置消息 (类型 11)，并返回一个表示成功的响应包
    """
    if not device_instance or not isinstance(req_json_data, dict):
        return
    # 11: 老协议teemo_G1
    # 0x7d: 新协议teemo_K1
    logger.debug("[*] 检测到位置消息 (类型 11 / 0x7d)，正在构造成功响应...")

    msg_type = kwargs.get('kwargs', 11)
    package_id = req_json_data.get('id')
    if not package_id:
        logger.error(f"params id invalid: {package_id}")
    data = req_json_data.get('data')
    if not data or not isinstance(data, list) or len(data) < 1:
        logger.error(f"params data invalid: {data}")
        return
    strategy = req_json_data.get('strategy')
    # if not strategy:
    #     logger.error(f"params strategy invalid: {strategy}")

    # 查找或创建设备
    location_package = LocationPackage.objects.create(
        device=device_instance,
        user=device_instance.user,
        msg_id=package_id,
        strategy=strategy,
        received_at=timezone.now()
    )

    if not location_package:
        logger.error(f"[!] 建立LocationPackage错误")

    for _data in data:
        if not isinstance(_data, dict):
            continue
        valid_wifi = ','.join([str(i) for i in _data.get('valid_wifi', {}).get('id', [])])
        power = _data.get('power', 0)
        stamp = _data.get('stamp', 0)
        signal = _data.get('signal', 0)
        reply_loc = _data.get('reply_loc', 0)
        sos = _data.get('sos', 0)
        geo = _data.get('geo', '')
        geo_data = ''
        isGps = _data.get('isGps', 0)
        gps_time_duration = _data.get('gps_time', {}).get('duration', 0)
        gps_time_type = _data.get('gps_time', {}).get('type', 0)
        gps_timeout = _data.get('gps_timeout', 0)
        search_count = _data.get('search_count', 0)
        wifi_1 = _data.get('wifi_1', 0)
        wifi_2 = _data.get('wifi_2', 0)
        wifi_3 = _data.get('wifi_3', 0)
        wifi_1_valid = _data.get('wifi_1_valid', 0)
        wifi_2_valid = _data.get('wifi_2_valid', 0)
        wifi_3_valid = _data.get('wifi_3_valid', 0)
        if geo:
            try:
                if isinstance(geo, str):
                    geo_data = NativeUtils.decrypt(base64.decodebytes(geo.encode('utf8')), 5)
                elif isinstance(geo, dict):
                    geo_data = json.dumps(geo)
                else:
                    geo_data = geo
            except:
                geo_data = ''
        LocationData.objects.create(
            package=location_package,
            # 数据点信息
            stamp=stamp,
            power=power,
            signal=signal,
            sos=sos,
            reply_loc=reply_loc,
            geo_encrypted=geo,
            geo_decrypted=geo_data,
            valid_wifis=valid_wifi,
            created_at=timezone.now()
        )
    response_packet = create_teemo_response_packet(11, {"status": 1, "msg": "", "id": package_id})
    return response_packet


@database_sync_to_async
def update_device_status_db(device_instance: WatchDevice, ping_data: dict, **kwargs):
    """
    使用 PING 包的数据更新数据库中的设备状态
    """
    if not device_instance or not isinstance(ping_data, dict):
        return

    logger.debug(f"[*] 正在为设备 {device_instance.udid} 更新 PING 状态...")
    device_instance.last_power = ping_data.get('power')
    device_instance.last_power_percent = ping_data.get('power_percent')
    device_instance.last_signal = ping_data.get('signal')
    device_instance.last_voltage = ping_data.get('voltage')
    device_instance.last_ping_time = timezone.now()
    device_instance.save(update_fields=[
        'last_power', 'last_power_percent', 'last_signal',
        'last_voltage', 'last_ping_time'
    ])
    logger.debug("[*] 设备状态更新完毕。")

    return create_teemo_response_packet(2, {"status": 1, "msg": ""})


@database_sync_to_async
def handle_status_msg(device_instance: WatchDevice, req_json_data: dict, **kwargs):
    logger.debug(f"[*] 正在为设备 {device_instance.udid} 更新 PING 状态...")
    charging = req_json_data.get('charging', 'off')
    if device_instance and device_instance.last_charging != charging:
        device_instance.last_ping_time = timezone.now()
        device_instance.last_charging = charging
        device_instance.save(update_fields=[
            'last_charging', 'last_ping_time'
        ])
    response_packet = create_teemo_response_packet(45, {"status": 1, "msg": ""})
    return response_packet


@database_sync_to_async
def handle_chat_message_db(device_instance: WatchDevice, json_payload: dict, **kwargs):
    """
    处理解析后的聊天消息，存入数据库，并返回 ACK 包。
    """
    if not device_instance or not json_payload:
        return None

    binary_payload = kwargs.get('binary_payload')

    message_id = json_payload.get('id')
    if not message_id:
        logger.error("[!] 聊天消息中缺少 'id' 字段。")
        return None

    # 1. 检查消息是否已存在，防止重复处理
    if ChatLog.objects.filter(device=device_instance, message_id=message_id).exists():
        logger.warning(f"[*] 收到重复的聊天消息 {message_id}，忽略处理。")
        # 即使是重复消息，也应该回复 ACK，防止客户端重传
        response_payload = {"id": message_id, "type": 122}
        return create_teemo_response_packet(0x03, response_payload)

    # 2. 解析并创建 ChatLog 对象
    try:
        content = json_payload.get('content', {})
        content_type = json_payload.get('content_type')

        chat_log_data = {
            'device': device_instance,
            'message_id': message_id,
            'chat_type': json_payload.get('chat_type'),
            'content_type': content_type,
            'from_user_id': json_payload.get('from_user_id'),
            'to_id': json_payload.get('to_id'),
            'stamp': json_payload.get('stamp'),
        }

        if content_type == ChatLog.ContentType.TEXT:
            chat_log_data['content_text'] = content.get('text')
        elif content_type == ChatLog.ContentType.VOICE:
            chat_log_data['voice_length'] = content.get('voice_length', 0)
            if binary_payload:
                # 定义存储路径
                voice_dir = os.path.join(settings.MEDIA_ROOT, 'voice_messages', device_instance.udid)
                os.makedirs(voice_dir, exist_ok=True)
                # 使用 message_id 作为文件名保证唯一性，后缀为 .amr
                file_name = f"{message_id}.amr"
                file_path = os.path.join(voice_dir, file_name)
                with open(file_path, 'wb') as f:
                    f.write(binary_payload)
                # 在数据库中存储相对路径
                chat_log_data['content_file_path'] = os.path.join('voice_messages', device_instance.udid, file_name)
                logger.debug(f"[*] 语音消息已保存至: {file_path}")

        # TODO: 在此添加对图片、视频、表情等其他类型的处理
        # elif content_type == ChatLog.ContentType.IMAGE:
        #     ...

        ChatLog.objects.create(**chat_log_data)
        logger.info(f"[*] 已成功保存来自 {device_instance.udid} 的聊天消息 {message_id}。")

    except Exception as e:
        logger.error(f"[!] 保存聊天消息 {message_id} 到数据库时出错: {e}")
        # 即使保存失败，也可能需要回复ACK，具体取决于业务逻辑
        # 这里我们选择不回复，让客户端有机会重试
        return None

    # 3. 构造并返回 ACK 确认包
    response_payload = {
        "id": message_id,
        "type": 122  # ACK包里的type字段是原始消息的类型
    }
    logger.debug(f"[*] 正在为消息 {message_id} 构造 ACK (类型 0x03) ...")
    return create_teemo_response_packet(0x03, response_payload)


async def handle_general_message(device_instance: WatchDevice, raw_payload: dict, **kwargs):
    logger.debug(f"[*] 处理 general 类型消息...")
    error_resp = None
    if not isinstance(raw_payload, dict):
        logger.error(f"[!] 消息payload类型错误: {raw_payload}")
        return error_resp
    if "sub_type" not in raw_payload:
        logger.error(f"[!] 消息payload数据错误, 'sub_type' 不存在: {raw_payload}")
        return error_resp
    try:
        sub_type = int(raw_payload["sub_type"])
    except ValueError as e:
        logger.error(f"[!] 消息payload数据错误, 'sub_type' 应为数字: {raw_payload}")
        return error_resp

    # logger.debug(f"[*] 子类型: {sub_type}")
    dispatcher = general_dispatcher.get(sub_type, {})
    logger.info(f"[*] 收到通用类型消息， {sub_type}: {dispatcher['type']}")
    if 'type' not in dispatcher or 'handler' not in dispatcher:
        logger.error(f"[!] 未知子类型: {sub_type}")
        return error_resp

    handler = dispatcher['handler']
    try:
        if asyncio.iscoroutinefunction(handler):
            return await handler(device_instance, raw_payload)
        else:
            return handler(device_instance, raw_payload)
    except Exception as e:
        logger.error(f"{e}")
        return error_resp


message_dispatcher = {
    0x14: {
        'type': 'login',
        'parser': parse_teemo_packet,
        'handler': handle_login_request_db,
    },
    0x01: {
        'type': 'ping',
        'parser': parse_teemo_packet,
        'handler': update_device_status_db,
    },
    0x0b: {
        'type': 'location',
        'parser': parse_teemo_packet,
        'handler': handle_location_msg,
    },
    0x7d: {
        'type': 'location',
        'parser': parse_teemo_zlib_packet,
        'handler': handle_location_msg,
    },
    0x2d: {
        'type': 'status',
        'parser': parse_teemo_packet,
        'handler': handle_status_msg,
    },
    0x34: {
        'type': 'call record',
        'parser': parse_teemo_packet,
        'handler': handle_call_record_db,
    },
    0x39: {
        'type': 'sms message',
        'parser': parse_teemo_packet,
        'handler': handle_sms_record_db,
    },
    0x7b: {
        'type': 'general',
        'parser': parse_teemo_packet,
        'handler': handle_general_message,
    },

    0x7a: {
        'type': 'chat',
        'parser': parse_chat_message_packet,
        'handler': handle_chat_message_db,
    }
}

general_dispatcher = {
    2: {
        'type': 'contact request',
        'parser': parse_teemo_packet,
        'handler': handle_contact_request_db,
    },
    20: {
        'type': 'weather',
        'parser': parse_teemo_packet,
        'handler': handle_weather_request,
    },
    32: {
        'type': 'weather',
        'parser': parse_teemo_packet,
        'handler': handle_apps_request,
    },
}


async def handle_client(reader, writer):
    """异步处理每个客户端连接"""
    addr = writer.get_extra_info('peername')
    logger.debug(f"\n[+] 接受来自 {addr[0]}:{addr[1]} 的新加密连接")

    # 在这个连接的生命周期内，保存设备实例
    device_instance = None
    buffer = b''  # 初始化一个空的接收缓冲区
    error_packet = create_teemo_response_packet(0x00, {"status": 0, "msg": "Unknown Error."})

    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                logger.debug(f"[-] 来自 {addr} 的连接已关闭 (EOF)。")
                break

            buffer += chunk
            logger.debug(f"[*] 收到 {len(chunk)} 字节数据，当前缓冲区大小: {len(buffer)}")

            while True:
                # 检查是否足够解析出长度头
                if len(buffer) < 3:
                    # 数据不够，跳出内层循环，等待下一次 read
                    break

                # 3 字节长度 (大端序)
                # 这个长度是 (版本+类型+payload) 的长度
                declared_body_length = struct.unpack('>i', b'\x00' + buffer[:3])[0]
                # 整个数据包的长度 = 3字节长度字段 + declared_body_length
                total_packet_length = 3 + declared_body_length

                # 检查缓冲区数据是否足够一个完整的包
                if len(buffer) < total_packet_length:
                    # 数据不够一个完整的包，跳出内层循环，等待下一次 read
                    logger.info(f"[*] 数据包不完整：需要 {total_packet_length} 字节，当前只有 {len(buffer)} 字节。等待更多数据...")
                    break

                packet_data = buffer[:total_packet_length]
                buffer = buffer[total_packet_length:]
                logger.debug(f"[*] 从缓冲区中提取了一个完整的包，长度为 {total_packet_length}。剩余缓冲区大小: {len(buffer)}")

                timestamp_data = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.debug(f"\n--- 正在处理TCP包于: {timestamp_data} ---")
                logger.debug(f"  原始数据: {packet_data}")
                logger.debug(f"  原始十六进制: {packet_data.hex()}")

                length, version, msg_type = struct.unpack('>i', b'\x00' + packet_data[:3])[0], packet_data[3], \
                                            packet_data[4]
                logger.debug(f"[*] 解析TCP包: 声明长度=0x{length:02x}, 版本=0x{version:02x}, 类型=0x{msg_type:02x}")

                dispatcher = message_dispatcher.get(msg_type, {})
                if 'type' not in dispatcher or 'parser' not in dispatcher or 'handler' not in dispatcher:
                    logger.error(f"[!] 未知消息类型: {msg_type}")
                    break

                logger.debug(f"[*] 收到 {msg_type:2x}: {dispatcher['type']} 消息")
                parser = dispatcher['parser']
                handler = dispatcher['handler']
                if not callable(parser) or not callable(handler):
                    logger.error(f"[!] parser or handler 类型错误")
                    break

                json_payload, byte_payload = parser(packet_data)
                response_packet = await handler(device_instance, json_payload, binary_payload=byte_payload, msg_type=msg_type)

                if 0x14 == msg_type and isinstance(response_packet, tuple) and 2 == len(response_packet):
                    instance, response_packet = response_packet
                    if instance and response_packet:
                        device_instance = instance
                        CLIENTS[device_instance.udid] = writer  # 注册
                        logger.info(f"[*] 设备 {device_instance.udid} 已注册到 TCP 服务器。当前连接数: {len(CLIENTS)}")

                if response_packet:
                    logger.debug(f"[*] 响应包:{response_packet[5:]}")
                    writer.write(response_packet)
                else:
                    logger.error("[*] 空响应包")
                    writer.write(error_packet)
                await writer.drain()
                logger.debug("[*] 响应包已发送。")

    except Exception as e:
        logger.error(f"[!] 处理来自 {addr} 的连接时发生错误: {e}")
    finally:
        if device_instance and device_instance.udid in CLIENTS:
            del CLIENTS[device_instance.udid]  # 注销
            logger.info(f"[*] 设备 {device_instance.udid} 已从 TCP 服务器注销。当前连接数: {len(CLIENTS)}")
        logger.info(f"[*] 关闭与 {addr} 的连接。")
        writer.close()


class Command(BaseCommand):
    help = 'Starts the custom SSL/TLS TCP server for Teemo watches'

    async def handle_async(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            # 降低安全等级以兼容旧设备
            context.set_ciphers('DEFAULT:@SECLEVEL=0')
            context.minimum_version = ssl.TLSVersion.TLSv1
            context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
            self.stdout.write(self.style.SUCCESS("[*] SSL context created with compatibility settings."))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"[!] Failed to create SSL context: {e}"))
            return

        server = await asyncio.start_server(
            handle_client, TCP_HOST, TCP_PORT, ssl=context)

        addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
        self.stdout.write(self.style.SUCCESS(f'[*] TLS/TCP 服务器正在 {addrs} 上监听...'))

        # 启动 Redis 监听器作为后台任务
        asyncio.create_task(redis_listener())

        async with server:
            await server.serve_forever()

    def handle(self, *args, **options):
        try:
            asyncio.run(self.handle_async())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n[*] 服务器已关闭。'))
