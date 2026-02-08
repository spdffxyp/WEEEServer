import os
import uuid
from json import JSONDecodeError

from django.core.files.storage import FileSystemStorage
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from rest_framework.decorators import api_view
from rest_framework.request import Request as DRFRequest
from datetime import datetime
import time
import json
import redis  # 使用同步 redis 库
import logging

from teemog1_api.models import WatchDevice, Contact


logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)


# 创建一个 Redis 连接池
redis_pool = redis.ConnectionPool(host='localhost', port=6379, db=0)


def notify_add_contact(udid: str, new_contact_user_id: int):
    """通过 Redis Pub/Sub 通知 TCP 服务器有新联系人添加"""
    try:
        r = redis.Redis(connection_pool=redis_pool)
        data = {'command': 'add_contact', 'udid': udid, 'contact_id': new_contact_user_id}
        message = json.dumps(data)
        r.publish("contacts_notify", message)
        print(f"[*] 已通过 Redis 发布添加联系人的通知: {message}")
    except Exception as e:
        print(f"[!] 发布 Redis 'add' 通知失败: {e}")


def print_request_details(req):
    """
    格式化并打印HTTP请求的详细信息，兼容 Django HttpRequest 和 DRF Request
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print("\n" + "=" * 50)
    print(f"--- HTTP 请求收到于: {timestamp} ---")

    is_drf_request = isinstance(req, DRFRequest)

    # 根据请求类型获取信息
    remote_addr = req.META.get('REMOTE_ADDR')
    method = req.method
    full_path = req.get_full_path()
    path = req.path

    print(f"来源 IP: {remote_addr}")
    print(f"方法: {method}")
    print(f"URL: {full_path}")
    print(f"路径: {path}")

    # 获取查询参数
    query_params = req.query_params if is_drf_request else req.GET
    if query_params:
        print("\n[查询参数]:")
        for key, value in query_params.items():
            print(f"  {key}: {value}")

    # 获取请求体
    try:
        data = req.data if is_drf_request else (json.loads(req.body) if req.body else None)
        if data:
            print("\n[请求体 (JSON)]:")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("\n[请求体]: (空)")
    except (json.JSONDecodeError, AttributeError):
         if hasattr(req, 'body') and req.body:
             print(f"\n[请求体 (Raw)]: {req.body}")
         else:
             print("\n[请求体]: (空)")

    print("=" * 50 + "\n")


@api_view(['GET'])
def get_apps(request):
    print_request_details(request)
    print("[*] 正在响应应用列表请求...")

    # 构造应用列表数据 (对应 AppStoreBean)
    app_list = [
        {
            "id": 1,
            "name": "聊天",
            "package_name": "com.sogou.teemo.watch.chat",
            "icon_url": "http://192.168.2.99:8000/static/icon/chat.png",  # 替换为你实际的图标地址
            "version": "1",
            "version_format": "1",
            "pkg_url": "http://192.168.2.99:8000/static/apk/chat.apk",  # 替换为实际APK下载地址
            "pkg_size": 1024 * 1024 * 5,  # 5MB，单位字节
            "pkg_hashcode": "md5_of_apk",  # 如果有校验逻辑，这里需要真实的MD5
            "status": 1,  # 状态码很重要，通常 0:下载 1:更新 3:打开 等，具体需测试
            "content_type": 1,
            "display_version": "1",
            "description": "这是聊天应用",
            "digest": "聊天应用简介"
        },
        {
            "id": 2,
            "name": "电话",
            "package_name": "com.sogou.teemo.watch.phone",
            "version": "1",
            "pkg_url": "",
            "status": 3  # 假设3是已安装/系统应用
        }
    ]

    apps_response = {
        "code": 200,
        "status": 200,  # 外层状态码，视框架而定，有些是 code: 0
        "msg": "success",
        "data": {
            # 对应 AppStoreServerBean
            "apps": {
                # 对应 AppStoreServerBean.Apps 内部类
                "data": app_list,  # <--- 这才是真正的列表，名字必须叫 data
                "page_index": 1,
                "page_size": 20,
                "total_count": len(app_list)
            },
            # 对应 AppStoreServerBean.installed_apps
            "installed_apps": []
        }
    }

    print(f"[*] 响应内容: {apps_response}")
    return JsonResponse(apps_response)


@api_view(['GET'])
def get_theme_info(request):
    print_request_details(request)
    print("[*] 正在响应主题信息请求...")
    theme_response = {
        "message": {"content": "成功", "notice": ""},
        "data": {"packages": [], "version": int(time.time())}
    }
    print(f"[*] 响应内容{theme_response}")
    return JsonResponse(theme_response)


@api_view(['GET'])
def get_dial_info(request):
    print_request_details(request)
    print("[*] 正在响应表盘信息请求...")
    dial_response = {
        "message": {"content": "成功", "notice": ""},
        "data": {"packages": [], "version": int(time.time())}
    }
    print(f"[*] 响应内容{dial_response}")
    return JsonResponse(dial_response)


@api_view(['GET'])
def get_emoticon_package_info(request):
    """
    处理获取表情包信息的请求。
    """
    print_request_details(request)
    print("[*] 正在响应表情包信息请求...")

    package_id_req = request.query_params.get('package', '1')

    # 构建符合 Java 端 EmojiPackageBean 和 EmojiBean 结构的响应数据
    emoticon_package_data = {
        "package_id": int(package_id_req),
        "name": "默认表情",
        "version": int(time.time()),
        "emoticons": [
            # {
            #     "id": "1_1",
            #     "tag": "[哈哈]",
            #     "url": "http://192.168.2.132:8000/static/emojis/haha.gif",
            #     "type": 1,
            #     "index": 1,
            #     "static_url": "http://192.168.2.132:8000/static/emojis/haha.png"
            # },
            # {
            #     "id": "1_2",
            #     "tag": "[可爱]",
            #     "url": "http://192.168.2.132:8000/static/emojis/keai.gif",
            #     "type": 1,
            #     "index": 2,
            #     "static_url": "http://192.168.2.132:8000/static/emojis/keai.png"
            # },
            # {
            #     "id": "1_3",
            #     "tag": "[飞吻]",
            #     "url": "http://192.168.2.132:8000/static/emojis/feiwen.gif",
            #     "type": 1,
            #     "index": 3,
            #     "static_url": "http://192.168.2.132:8000/static/emojis/feiwen.png"
            # },
            # {
            #     "id": "1_4",
            #     "tag": "[白眼]",
            #     "url": "http://192.168.2.132:8000/static/emojis/baiyan.gif",
            #     "type": 1,
            #     "index": 4,
            #     "static_url": "http://192.168.2.132:8000/static/emojis/baiyan.png"
            # }
        ]
    }

    # 包装在顶层结构中
    response_data = {
        "message": {"content": "成功", "notice": ""},
        "data": emoticon_package_data
    }

    print(f"[*] 响应内容: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
    return JsonResponse(response_data)


@api_view(['GET'])
def get_version(request):
    print_request_details(request)
    print("[*] 正在响应版本检查请求...")
    version_response = {
        "message": {"content": "已经是最新版本", "notice": ""},
        "data": {}
    }
    print(f"[*] 响应内容{version_response}")
    return JsonResponse(version_response)


@api_view(['POST'])
def add_contact(request):
    print_request_details(request)
    print("[*] 正在处理添加联系人请求...")

    token = request.data.get('token') or request.query_params.get('token')
    baby_id = request.data.get('user_id') or request.query_params.get('user_id')
    name = request.data.get('name') or request.query_params.get('name')
    phone = request.data.get('phone') or request.query_params.get('phone')
    ext_json = request.data.get('ext', '[]') or request.query_params.get('ext', '[]')   # 可选的 ext 字段

    # 验证设备
    try:
        device = WatchDevice.objects.get(http_token=token, baby_id=baby_id)
    except WatchDevice.DoesNotExist:
        print("[!] 添加联系人失败：设备 token 无效。")
        return JsonResponse({"code": 403, "message": "认证失败"}, status=403)

    # 检查号码是否重复 (可选但推荐)
    if Contact.objects.filter(device=device, phone=phone).exists():
        return JsonResponse({"code": 400, "message": "该号码已存在"}, status=400)

    try:
        # 创建新联系人
        new_contact = Contact.objects.create(
            device=device,
            # 使用时间戳生成一个唯一的 user_id
            user_id=int(time.time() * 1000),
            name=name,
            phone=phone,
            contacts_type=Contact.ContactType.NORMAL,  # 默认添加为普通联系人
            auth=7  # 默认可见
        )

        # 处理 ext 字段
        try:
            ext_list = json.loads(ext_json)
            new_contact.set_ext_phones(ext_list)
        except JSONDecodeError:
            new_contact.set_ext_phones([])
        new_contact.save()

        print(f"[*] 联系人 '{name}' (ID: {new_contact.user_id}) 添加成功。")

        # 发布通知，通过tcp连接推送联系人
        notify_add_contact(device.udid, new_contact.user_id)

        # 返回成功的响应，必须包含新联系人的 id
        success_response = {
            "code": 200,
            "message": "添加成功",
            "data": {
                "id": new_contact.user_id
            }
        }
        return JsonResponse(success_response)

    except Exception as e:
        print(f"[!] 添加联系人时发生数据库错误: {e}")
        return JsonResponse({"code": 500, "message": "服务器内部错误"}, status=500)


@api_view(['POST'])
def chat_image_upload(request):
    # 从查询参数中获取设备信息
    token = request.GET.get('token')
    udid = request.GET.get('sn')  # 手表使用 sn 参数传递 UDID

    if not token or not udid:
        logger.error(f"[/chat/image/upload.do] Missing 'token' or 'sn' in query parameters.")
        return JsonResponse({"code": 401, "msg": "Authentication required."}, status=401)

    # 验证设备
    try:
        device = WatchDevice.objects.get(udid=udid, http_token=token)
        logger.info(f"[/chat/image/upload.do] Authenticated device: {udid}")
    except WatchDevice.DoesNotExist:
        logger.error(f"[/chat/image/upload.do] Authentication failed for device: {udid} with token: {token}")
        return JsonResponse({"code": 403, "msg": "Invalid token or device."}, status=403)

    # 处理上传的文件
    # 根据Java源码 `ChatRemoteDataSource.java` 中的 `upload` 方法, 文件字段名是 "file"
    if 'file' not in request.FILES:
        logger.error(f"[/chat/image/upload.do] No 'file' found in the request.")
        return JsonResponse({"code": 400, "msg": "No file uploaded."}, status=400)

    uploaded_file = request.FILES['file']

    # 构建保存路径
    # media/image_messages/UDID/timestamp_filename.jpg
    fs = FileSystemStorage()
    relative_dir = os.path.join('image_messages', udid)
    # 使用时间戳确保文件名唯一
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{timestamp}_{uploaded_file.name}"

    # 保存文件并获取相对路径
    saved_path = fs.save(os.path.join(relative_dir, file_name), uploaded_file)

    # 构建可访问的 URL
    file_url = fs.url(saved_path)

    logger.info(f"[/chat/image/upload.do] Image saved for {udid} at: {saved_path}")
    logger.info(f"[/chat/image/upload.do] Accessible URL: {file_url}")

    # 根据Java源码 `ChatPresenter.onResponse` 的逻辑，构造成功的响应
    # 它需要一个包含 image_id, small_url, large_url, origin_url 等字段的 data 对象

    # 在这个简单的实现中，我们让所有 URL 都指向同一个文件
    # image_id 可以用文件的相对路径来唯一标识
    response_data = {
        "image_id": saved_path,
        "small_url": file_url,
        "large_url": file_url,
        "origin_url": file_url,
        "height": request.GET.get('height', 0),
        "width": request.GET.get('width', 0),
        "size": uploaded_file.size,
    }

    # 最终的响应格式是 {"code": 200, "msg": "...", "data": {...}}
    return JsonResponse({
        "code": 200,
        "msg": "Upload successful",
        "data": response_data
    })


@api_view(['POST'])
def delete_contact(request):
    print_request_details(request)
    print("[*] 正在处理删除联系人请求...")

    token = request.data.get('token') or request.query_params.get('token')
    baby_id = request.data.get('user_id') or request.query_params.get('user_id')
    contact_user_id = request.data.get('id') or request.query_params.get('id')

    # 验证设备
    try:
        device = WatchDevice.objects.get(http_token=token, baby_id=baby_id)
        contact_to_delete = Contact.objects.get(device=device, user_id=contact_user_id)
    except (WatchDevice.DoesNotExist, Contact.DoesNotExist):
        print("[!] 删除联系人失败：设备 token 无效或联系人不存在。")
        # 即使找不到，也返回成功，避免手表端卡住
        return JsonResponse({"code": 200, "message": "联系人不存在，操作视为成功"})

    try:
        contact_name = contact_to_delete.name
        contact_to_delete.delete()
        print(f"[*] 联系人 '{contact_name}' (ID: {contact_user_id}) 删除成功。")

        # 发布通知
        # 实测delete联系人不用推送

        # 返回成功的响应
        success_response = {
            "code": 200,
            "message": "删除成功",
            "data": {}
        }
        return JsonResponse(success_response)

    except Exception as e:
        print(f"[!] 删除联系人时发生数据库错误: {e}")
        return JsonResponse({"code": 500, "message": "服务器内部错误"}, status=500)


@api_view(['POST'])  # 限制只接受 POST 请求
def update_contact(request):
    print_request_details(request)
    print("[*] 正在处理联系人更新请求...")

    # 从 POST 表单数据中获取参数
    token = request.data.get('token') or request.query_params.get('token')
    baby_id = request.data.get('user_id') or request.query_params.get('user_id')  # 注意 Java 代码里用的是 'user_id'
    contact_user_id = request.data.get('id') or request.query_params.get('id')

    # 简单的 token 和 user_id 验证
    try:
        device = WatchDevice.objects.get(http_token=token, baby_id=baby_id)
        contact_to_update = Contact.objects.get(device=device, user_id=contact_user_id)
    except (WatchDevice.DoesNotExist, Contact.DoesNotExist):
        print("[!] 更新联系人失败：设备 token 无效或联系人不存在。")
        return JsonResponse({"code": 403, "message": "认证失败或联系人不存在"}, status=403)

    # 根据请求中的字段更新联系人对象
    try:
        if 'name' in request.data:
            contact_to_update.name = request.data['name']
        elif 'name' in request.query_params:
            contact_to_update.name = request.query_params['name']
        if 'phone' in request.data:
            contact_to_update.phone = request.data['phone']
        elif 'phone' in request.query_params:
            contact_to_update.phone = request.query_params['phone']
        if 'photo' in request.data:
            contact_to_update.photo = request.data['photo']
        elif 'photo' in request.query_params:
            contact_to_update.photo = request.query_params['photo']
        if 'ext' in request.data or 'ext' in request.query_params:
            # Java端传来的是 JSON 字符串，我们需要解析
            ext_json_str = request.data.get('ext') or request.query_params.get('ext')
            try:
                ext_list = json.loads(ext_json_str)
                contact_to_update.set_ext_phones(ext_list)
            except JSONDecodeError:
                contact_to_update.set_ext_phones([])

        # ... 你可以根据需要添加对其他字段（如 spell, gender 等）的更新 ...

        contact_to_update.save()
        print(f"[*] 联系人 {contact_to_update.name} (ID: {contact_user_id}) 更新成功。")

        # 发布通知
        # 实测update联系人不用推送

        # 返回成功的响应
        success_response = {
            "code": 200,
            "message": "更新成功",
            "data": {}  # data 字段可以为空
        }
        return JsonResponse(success_response)

    except Exception as e:
        print(f"[!] 更新联系人时发生数据库错误: {e}")
        return JsonResponse({"code": 500, "message": "服务器内部错误"}, status=500)

# ########### 糖猫android客户端


@api_view(['GET'])
def passport_login(request):
    print_request_details(request)
    print("[*] 正在响应 Passport 登录请求...")

    # 1. 从请求中获取关键参数，必须原样返回
    # App 发送了 stamp 和 timestamp 两个参数，内容一样，我们取一个即可
    client_stamp = request.query_params.get('stamp')
    if not client_stamp:
        client_stamp = request.query_params.get('timestamp')

    client_udid = request.query_params.get('udid', '')
    client_sgid = request.query_params.get('sgid', '')

    # 2. 生成服务器端的数据
    # 生成一个唯一的 session token，这是最重要的字段
    session_token = f"fake-token-{uuid.uuid4()}"

    # 生成服务器当前的时间戳 (毫秒)
    server_timestamp_ms = str(int(time.time() * 1000))

    # 3. 构造 PassportLoginBean 对应的数据 payload
    passport_data = {
        # --- 关键字段 ---
        "token": session_token,
        "user_id": "fake_user_from_server_001",

        # --- 流程控制字段 ---
        "profile_completed": 1,  # 1 = 已完善资料，App会进入主页
        "timo_binded": 1,  # 1 = 已绑定手表，App会进入主页

        # --- 必须原样返回的字段 ---
        "client_stamp": client_stamp,
        "client_udid": client_udid,
        "client_sgid": client_sgid,
        "client_device": "android",

        # --- 其他字段 ---
        "service_stamp": server_timestamp_ms,
        "client_token": ""  # 这个字段似乎没用，可以返回空字符串
    }

    # 4. 构造最外层的 HttpData 包装对象
    final_response = {
        "code": 200,
        "msg": "登录成功",
        "data": passport_data
    }

    print(f"[*] 响应内容: {final_response}")
    return JsonResponse(final_response)


@api_view(['GET'])
def android_client_user_info(request):
    print_request_details(request)
    print("[*] 正在响应 Passport 登录请求...")

    # 1. 从请求中获取关键参数，必须原样返回
    # App 发送了 stamp 和 timestamp 两个参数，内容一样，我们取一个即可
    client_stamp = request.query_params.get('stamp')
    if not client_stamp:
        client_stamp = request.query_params.get('timestamp')

    client_udid = request.query_params.get('udid', '')
    client_sgid = request.query_params.get('sgid', '')

    # 2. 生成服务器端的数据
    # 生成一个唯一的 session token，这是最重要的字段
    session_token = f"fake-token-{uuid.uuid4()}"

    # 生成服务器当前的时间戳 (毫秒)
    server_timestamp_ms = str(int(time.time() * 1000))

    # 3. 构造 PassportLoginBean 对应的数据 payload
    passport_data = {
        # --- 关键字段 ---
        "token": session_token,
        "user_id": "fake_user_from_server_001",

        # --- 流程控制字段 ---
        "profile_completed": 1,  # 1 = 已完善资料，App会进入主页
        "timo_binded": 1,  # 1 = 已绑定手表，App会进入主页

        # --- 必须原样返回的字段 ---
        "client_stamp": client_stamp,
        "client_udid": client_udid,
        "client_sgid": client_sgid,
        "client_device": "android",

        # --- 其他字段 ---
        "service_stamp": server_timestamp_ms,
        "client_token": ""  # 这个字段似乎没用，可以返回空字符串
    }

    # 4. 构造最外层的 HttpData 包装对象
    final_response = {
        "code": 200,
        "msg": "登录成功",
        "data": passport_data
    }

    print(f"[*] 响应内容: {final_response}")
    return JsonResponse(final_response)


def catch_all(request, path):
    print_request_details(request)
    print(f"[!] 未处理的HTTP请求: {path}")
    return HttpResponse(f"未处理的HTTP请求: {path}", status=200)