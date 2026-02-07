from django.db import models
from django.contrib.auth.models import User
import uuid
import json


class WatchDevice(models.Model):
    # 与 Django 内置用户关联，一个用户可以有多个设备
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    # 手表硬件信息
    udid = models.CharField(max_length=100, unique=True, db_index=True, help_text="设备唯一识别码")
    imei = models.CharField(max_length=50, blank=True, null=True)
    imsi = models.CharField(max_length=50, blank=True, null=True)
    # ssn 在 miscdata 分区，PhaseCheckParse 类会读取这个文件的内容，从第68个字节开始，读取64个字节，最后截取前46个字符作为 ssn 的值
    ssn = models.CharField(max_length=200, blank=True, null=True)
    mac = models.CharField(max_length=32, blank=True, null=True)
    iccid = models.CharField(max_length=32, blank=True, null=True, verbose_name="ICCID")

    # 激活和会话信息
    baby_id = models.BigIntegerField(unique=True, help_text="手表用户的唯一ID")
    http_token = models.UUIDField(default=uuid.uuid4, editable=False, help_text="用于HTTP API认证的Token")
    # 手表是否已经绑定， True: 绑定, False: 未绑定
    is_bound = models.BooleanField(default=False)
    # 手表是否已经停用， True: 停用, False: 正常
    is_halted = models.BooleanField(default=False)

    # 其他信息
    last_login = models.DateTimeField(auto_now=True)
    device_version = models.CharField(max_length=50, blank=True, null=True)
    # 服务号码
    # SmsReceiver.java 中，手表可能会向这个号码发送包含加密后IMSI的短信
    service_number = models.CharField(max_length=50, blank=True, null=True)

    # status
    last_power = models.IntegerField(default=0, null=True, blank=True, help_text="最后一次上报的电量等级")
    last_power_percent = models.IntegerField(default=0, null=True, blank=True, help_text="最后一次上报的电量百分比")
    last_signal = models.IntegerField(default=0, null=True, blank=True, help_text="最后一次上报的信号强度")
    last_voltage = models.IntegerField(default=0, null=True, blank=True, help_text="最后一次上报的电压")
    last_ping_time = models.DateTimeField(null=True, blank=True, help_text="最后一次 PING 的时间")
    last_charging = models.CharField(max_length=8, default="off", null=True, blank=True, help_text="最后一次上报的充电状态")

    def __str__(self):
        return f"Device {self.udid} (Baby ID: {self.baby_id})"


class LocationPackage(models.Model):
    # 与 Django 内置用户关联，一个用户可以有多个设备
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='location_packages')
    device = models.ForeignKey(WatchDevice, on_delete=models.SET_NULL, null=True, related_name='location_packages')
    # 定位信息
    msg_id = models.CharField(max_length=50, help_text="手表端生成的数据包ID")
    strategy = models.IntegerField(default=0, blank=True, null=True, help_text="定位策略")
    # 自动记录创建时间，便于排序和追踪
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"Package {self.msg_id} from {self.device.udid}"

    class Meta:
        # 按接收时间倒序排列
        ordering = ['-received_at']


class LocationData(models.Model):
    package = models.ForeignKey(LocationPackage, on_delete=models.CASCADE, related_name='data_points')
    # 数据点信息
    stamp = models.BigIntegerField(help_text="数据点的时间戳 (秒)")
    power = models.IntegerField(null=True, blank=True, help_text="电量")
    signal = models.IntegerField(null=True, blank=True, help_text="信号强度")
    sos = models.IntegerField(default=0, help_text="SOS状态, 0: 否, 1: 是")
    reply_loc = models.IntegerField(null=True, blank=True, help_text="定位上报类型")
    isGps = models.IntegerField(null=True, blank=True, default=0)
    gps_time_duration = models.IntegerField(null=True, blank=True, default=0)
    gps_time_type = models.IntegerField(null=True, blank=True, default=0)
    gps_timeout = models.IntegerField(null=True, blank=True, default=0)
    search_count = models.IntegerField(null=True, blank=True, default=0)
    wifi_1 = models.IntegerField(null=True, blank=True, default=0)
    wifi_2 = models.IntegerField(null=True, blank=True, default=0)
    wifi_3 = models.IntegerField(null=True, blank=True, default=0)
    wifi_1_valid = models.IntegerField(null=True, blank=True, default=0)
    wifi_2_valid = models.IntegerField(null=True, blank=True, default=0)
    wifi_3_valid = models.IntegerField(null=True, blank=True, default=0)

    # 使用 TextField 存储可能很长的字符串
    geo_encrypted = models.TextField(blank=True, help_text="加密后的原始geo数据")
    geo_decrypted = models.TextField(blank=True, help_text="解密后的geo数据 (JSON格式)")
    valid_wifis = models.TextField(blank=True, help_text="有效的Wi-Fi信息 (JSON格式)")

    # 自动记录时间
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        # 将时间戳转换为可读格式
        from datetime import datetime
        dt_object = datetime.fromtimestamp(self.stamp)
        return f"Location at {dt_object.strftime('%Y-%m-%d %H:%M:%S')}"

    class Meta:
        ordering = ['stamp']


class Contact(models.Model):
    # --- 关联关系 ---
    # 一个联系人属于一个设备
    device = models.ForeignKey(WatchDevice, on_delete=models.CASCADE, related_name='contacts', help_text="所属设备")

    # --- 联系人核心信息 ---
    user_id = models.BigIntegerField(unique=True, db_index=True, help_text="联系人的唯一ID（来自手表或服务器）")
    name = models.CharField(max_length=50, help_text="姓名")
    phone = models.CharField(max_length=30, help_text="主电话号码")

    # 使用 TextField 存储 JSON 格式的额外号码列表，更灵活
    ext = models.TextField(null=True, blank=True, help_text='额外电话号码 (JSON list)')

    # --- 分类与权限 ---
    class ContactType(models.IntegerChoices):
        NORMAL = 1, '普通联系人'
        FAMILY = 2, '家人'
        FRIEND = 3, '好友'

    # 家人类型，在设备端不可编辑，其他类型可编辑
    contacts_type = models.IntegerField(choices=ContactType.choices, default=ContactType.NORMAL, help_text="联系人类型")

    # 权限位，默认为 7 (二进制 111)，确保可见
    auth = models.IntegerField(default=7, null=True, blank=True, help_text="权限位")

    # --- 个人资料 ---
    photo = models.URLField(max_length=512, null=True, blank=True, help_text="头像图片的URL")

    class GenderType(models.IntegerChoices):
        UNKNOWN = 0, '未知'
        MALE = 1, '男'
        FEMALE = 2, '女'

    gender = models.IntegerField(choices=GenderType.choices, default=GenderType.UNKNOWN, null=True, blank=True)
    birthday = models.IntegerField(null=True, blank=True, help_text="生日，格式为 YYYYMMDD")

    # --- 关系与状态 ---
    admin = models.IntegerField(default=0, help_text="是否是管理员 (通常用于家人)")
    # com.sogou.teemo.watch.phone.receiver.TcpReceiver.contactsSave
    # 设备端设置，将device_type为2的联系人设置为2，其余的设置为1
    # role_type = models.IntegerField(null=True, blank=True, help_text="角色类型")

    # 设备类型，0 和 1 在家人分组中可能不显示，所以默认给个其他值
    # 如果admin为1则为100， 否则为2
    # device_type = models.IntegerField(default=2, null=True, blank=True)

    # --- 内部字段 ---
    spell = models.CharField(max_length=100, null=True, blank=True, help_text="姓名拼音首字母，用于排序")
    profile = models.TextField(null=True, blank=True, help_text="家人分组的Profile信息 (JSON)")
    created_at = models.DateTimeField(auto_now_add=True)

    # 辅助方法，用于处理 ext 字段的存取
    def set_ext_phones(self, phones: list):
        self.ext = json.dumps(phones)

    def get_ext_phones(self) -> list:
        if not self.ext:
            return []
        try:
            return json.loads(self.ext)
        except json.JSONDecodeError:
            return []

    def __str__(self):
        return f"{self.name} ({self.phone}) on Device {self.device.udid}"

    class Meta:
        # 确保同一个设备下的联系人 user_id 是唯一的
        unique_together = ('device', 'user_id')
        ordering = ['spell', 'name']  # 默认按拼音和姓名排序


class CallRecord(models.Model):
    # 关联到哪个设备
    device = models.ForeignKey(WatchDevice, on_delete=models.CASCADE, related_name='call_records')
    # 关联到哪个联系人（如果能匹配到的话）
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True)

    # 从 RecordBean 映射过来的字段
    record_id = models.BigIntegerField(unique=True, help_text="手表端生成的唯一记录ID")
    phone_number = models.CharField(max_length=30)
    name = models.CharField(max_length=50, blank=True, null=True)

    class CallType(models.IntegerChoices):
        OUTGOING = 0, '呼出'
        INCOMING = 1, '呼入'
        LISTEN = 2, '超能听'
        MISSED = 3, '未接'

    call_type = models.IntegerField(choices=CallType.choices, help_text="通话类型")

    stamp = models.DateTimeField(help_text="通话发生的时间戳")
    duration = models.IntegerField(default=0, help_text="通话时长（秒）")

    # 原始 geo 数据，我们直接存 JSON 字符串，不去解密
    geo_data_json = models.TextField(blank=True, null=True)

    # 其他元数据
    is_read = models.BooleanField(default=False)
    is_sync = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Call to/from {self.name or self.phone_number} on {self.stamp}"

    class Meta:
        ordering = ['-stamp']  # 默认按时间倒序排列


class ChatLog(models.Model):
    """存储手表上报的聊天记录"""
    class ContentType(models.IntegerChoices):
        VOICE = 1, '语音'
        TEXT = 2, '文本'
        IMAGE = 3, '图片'
        EMOJI = 4, '表情'
        VIDEO = 6, '视频'

    device = models.ForeignKey(WatchDevice, on_delete=models.CASCADE, related_name='chat_logs', verbose_name="关联设备")
    message_id = models.CharField(max_length=100, unique=True, db_index=True, verbose_name="消息ID")
    chat_type = models.IntegerField(verbose_name="聊天类型")
    content_type = models.IntegerField(choices=ContentType.choices, verbose_name="内容类型")
    from_user_id = models.BigIntegerField(verbose_name="发送方ID")
    to_id = models.BigIntegerField(verbose_name="接收方ID")
    stamp = models.BigIntegerField(verbose_name="消息时间戳")
    received_at = models.DateTimeField(auto_now_add=True, verbose_name="服务器接收时间")

    # 根据内容类型存储数据
    content_text = models.TextField(blank=True, null=True, verbose_name="文本内容")
    content_file_path = models.CharField(max_length=255, blank=True, null=True, verbose_name="媒体文件路径")
    voice_length = models.IntegerField(default=0, verbose_name="语音时长(秒)")

    class Meta:
        verbose_name = "聊天记录"
        verbose_name_plural = verbose_name
        ordering = ['-stamp']

    def __str__(self):
        return f"Chat from {self.from_user_id} to {self.to_id} ({self.get_content_type_display()})"


class SmsMessage(models.Model):
    """短信记录"""
    device = models.ForeignKey(WatchDevice, on_delete=models.CASCADE, related_name='sms_logs', verbose_name="关联设备")
    message = models.TextField(blank=True, null=True, verbose_name="文本内容")
    phone = models.CharField(max_length=30, help_text="电话号码")
    error_cause = models.CharField(max_length=16, verbose_name="错误码")
    stamp = models.DateTimeField(verbose_name="消息时间戳")

    class Meta:
        verbose_name = "短信记录"
        verbose_name_plural = verbose_name
        ordering = ['-stamp']

    def __str__(self):
        return f"{self.phone}：{self.message[:10]}"

