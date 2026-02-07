from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from datetime import datetime

from django.utils.text import Truncator

from .models import WatchDevice, LocationPackage, LocationData, Contact, CallRecord, ChatLog, SmsMessage


# --- 1. 定制 LocationPackage 的管理界面 (保持不变或简化) ---
# 这个界面现在主要用于单独查看数据包详情
@admin.register(LocationPackage)
class LocationPackageAdmin(admin.ModelAdmin):
    list_display = ('msg_id', 'device_link', 'received_at', 'data_points_count')
    list_filter = ('received_at', 'device')
    search_fields = ('msg_id', 'device__udid')
    readonly_fields = ('device', 'msg_id', 'strategy', 'received_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='关联设备')
    def device_link(self, obj):
        if obj.device:
            url = reverse("admin:teemog1_api_watchdevice_change", args=[obj.device.pk])
            return mark_safe(f'<a href="{url}">{obj.device.udid}</a>')
        return "N/A"

    @admin.display(description='数据点数量')
    def data_points_count(self, obj):
        return obj.data_points.count()


# --- 2. 定制 LocationData 的管理界面 (保持不变或简化) ---
# 这个界面主要用于单独查看所有定位数据点
@admin.register(LocationData)
class LocationDataAdmin(admin.ModelAdmin):
    ordering = ('-stamp',)
    list_display = ('stamp_formatted', 'package_link', 'power', 'signal', 'sos')
    readonly_fields = [field.name for field in LocationData._meta.fields]
    list_filter = ('created_at',)
    search_fields = ('package__device__udid',)  # 允许通过设备UDID搜索

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='所属数据包')
    def package_link(self, obj):
        if obj.package:
            url = reverse("admin:teemog1_api_locationpackage_change", args=[obj.package.pk])
            return mark_safe(f'<a href="{url}">{obj.package.msg_id}</a>')
        return "N/A"

    @admin.display(description='时间', ordering='stamp')
    def stamp_formatted(self, obj):
        if obj.stamp:
            return datetime.fromtimestamp(obj.stamp).strftime('%Y-%m-%d %H:%M:%S')
        return "N/A"


# --- 3. 定制 WatchDevice 的管理界面 (核心修改) ---
@admin.register(WatchDevice)
class WatchDeviceAdmin(admin.ModelAdmin):
    # 在列表页中显示的字段
    list_display = (
        'udid',
        'baby_id',
        'is_bound',
        'user',
        'last_login',
        'device_version',
    )

    # 在列表页中可以作为链接点击进入详情页的字段
    list_display_links = ('udid', 'baby_id')

    # 在列表页右侧提供筛选器
    list_filter = ('is_bound', 'is_halted', 'device_version')

    # 在列表页顶部提供搜索框，可按指定字段搜索
    search_fields = ('udid', 'imei', 'ssn', 'baby_id')

    # 在详情页中将字段分组显示
    fieldsets = (
        ('核心身份信息', {
            'fields': ('udid', 'baby_id', 'is_bound', 'is_halted', 'user')
        }),
        ('硬件与会话信息', {
            'fields': ('imei', 'mac', 'imsi', 'ssn', 'http_token', 'device_version', 'last_login')
        }),
        ('状态信息', {
            'fields': ('last_charging', 'last_power', 'last_power_percent', 'last_signal', 'last_voltage', 'last_ping_time')
        }),
        ('最新定位记录', {
            'fields': ('display_latest_locations',),
        }),
    )

    # 在详情页中，只读字段（不可编辑）
    readonly_fields = (
        # 'user',
        'udid',
        'imei',
        'imsi',
        'ssn',
        'mac',
        'baby_id',
        'http_token',
        # 'is_bound',
        # 'is_halted',
        'last_login',
        'device_version',
        'service_number',
        'last_power',
        'last_power_percent',
        'last_signal',
        'last_voltage',
        'last_ping_time',
        'last_charging',
        'display_latest_locations'
    )

    # 默认排序方式，'-'表示降序
    ordering = ('-last_login',)

    @admin.display(description='定位历史 (点击时间可查看详情)')  # 修改描述以提示用户
    def display_latest_locations(self, obj):
        locations = LocationData.objects.filter(package__device=obj).order_by('-stamp')[:10]

        if not locations:
            return "无定位记录"

        html = """
        <style>
            .location-table { width: 100%; border-collapse: collapse; }
            .location-table th, .location-table td { 
                border: 1px solid #ccc; 
                padding: 8px; 
                text-align: left; 
            }
            .location-table th { background-color: #f2f2f2; }
            .location-table a { color: #007bff; text-decoration: none; }
            .location-table a:hover { text-decoration: underline; }
        </style>
        <table class="location-table">
            <thead>
                <tr>
                    <th>时间</th>
                    <th>电量</th>
                    <th>信号</th>
                    <th>SOS</th>
                    <th>GEO (加密, 前30位)</th>
                </tr>
            </thead>
            <tbody>
        """

        for loc in locations:
            # 1. 获取 LocationData 详情页的 URL
            # 'admin:app名_模型名_change' 是 Django Admin URL 的命名规则
            # loc.pk 是 LocationData 实例的主键
            location_data_url = reverse("admin:teemog1_api_locationdata_change", args=[loc.pk])

            timestamp = datetime.fromtimestamp(loc.stamp).strftime('%Y-%m-%d %H:%M:%S') if loc.stamp else 'N/A'
            power = loc.power if loc.power is not None else 'N/A'
            signal = loc.signal if loc.signal is not None else 'N/A'
            sos = '是' if loc.sos == 1 else '否'
            geo_preview = (loc.geo_decrypted[:30] + '...') if loc.geo_decrypted and len(
                loc.geo_decrypted) > 30 else loc.geo_decrypted

            # 2. 将时间戳单元格包装在 <a> 标签中
            html += f"""
                <tr>
                    <td><a href="{location_data_url}" target="_blank">{timestamp}</a></td>
                    <td>{power}</td>
                    <td>{signal}</td>
                    <td>{sos}</td>
                    <td>{geo_preview}</td>
                </tr>
            """

        html += "</tbody></table>"

        return mark_safe(html)


@admin.register(Contact)
class ContactsAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'contacts_type', 'device')
    search_fields = ('name', 'phone')
    list_filter = ('device', 'contacts_type')

    # 辅助方法，让 ext 字段在后台显示更友好
    def get_ext_phones_display(self, obj):
        return ", ".join(obj.get_ext_phones())

    get_ext_phones_display.short_description = '额外号码'

    # 将辅助方法添加到显示列表中
    list_display += ('get_ext_phones_display',)

    @admin.register(CallRecord)
    class CallRecordAdmin(admin.ModelAdmin):
        # list_display 控制在列表页显示哪些字段
        list_display = (
            'name',
            'phone_number',
            'call_type',
            'duration_display',  # 使用一个自定义方法来美化时长显示
            'stamp',
            'device'
        )

        # list_filter 在右侧提供一个过滤器
        list_filter = ('call_type', 'device')

        # search_fields 在顶部提供一个搜索框
        search_fields = ('name', 'phone_number', 'device__udid')

        # readonly_fields 指定哪些字段在详情页是只读的
        readonly_fields = ('device', 'contact', 'name', 'phone_number', 'call_type', 'duration', 'stamp',
                           'record_id', 'geo_data_json')

        # fieldsets 用于在详情页对字段进行分组
        fieldsets = (
            ('基本信息', {
                'fields': ('device', 'contact', 'name', 'phone_number')
            }),
            ('通话详情', {
                'fields': ('call_type', 'duration', 'stamp')
            }),
            ('原始数据', {
                'classes': ('collapse',),  # 'collapse' 表示默认折叠
                'fields': ('record_id', 'geo_data_json'),
            }),
        )

        # 自定义方法，用于在列表页更友好地显示通话时长
        def duration_display(self, obj):
            if obj.duration is None:
                return "N/A"
            minutes, seconds = divmod(obj.duration, 60)
            return f"{minutes:02d}:{seconds:02d}"

        duration_display.short_description = '通话时长'  # 设置列标题


@admin.register(ChatLog)
class ChatLogAdmin(admin.ModelAdmin):
    # 列表页显示哪些字段
    list_display = (
    'device', 'from_to_display', 'get_content_type_display', 'content_summary', 'formatted_stamp', 'received_at')

    # 列表页右侧的过滤器
    list_filter = ('device', 'content_type', 'chat_type', 'received_at')

    # 顶部搜索框可以搜索的字段
    search_fields = ('message_id', 'from_user_id', 'to_id', 'content_text', 'device__udid')

    # 详情页的字段布局
    fieldsets = (
        ('消息概览', {
            'fields': ('device', 'message_id', 'from_to_display', 'formatted_stamp', 'received_at')
        }),
        ('消息内容', {
            'fields': ('get_content_type_display', 'chat_type', 'content_summary_detail')
        }),
        ('原始数据', {
            'fields': ('content_text', 'content_file_path', 'voice_length'),
            'classes': ('collapse',),  # 默认折叠此部分
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        # 使所有模型字段在详情页中都为只读，并包括自定义方法
        if obj:
            return [field.name for field in self.model._meta.fields] + \
                   ['from_to_display', 'formatted_stamp', 'content_summary_detail']
        return []

    # 自定义方法，用于 list_display 和 fieldsets
    @admin.display(description='发送方 -> 接收方')
    def from_to_display(self, obj):
        return f"{obj.from_user_id} -> {obj.to_id}"

    @admin.display(description='消息时间戳', ordering='-stamp')
    def formatted_stamp(self, obj):
        if obj.stamp:
            # 手表上报的时间戳通常是毫秒级的
            try:
                return datetime.fromtimestamp(obj.stamp / 1000).strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                return "时间戳无效"
        return '-'

    @admin.display(description='内容摘要')
    def content_summary(self, obj):
        """用于列表页的简短摘要"""
        if obj.content_type == ChatLog.ContentType.TEXT:
            return Truncator(obj.content_text).chars(40)  # 截断长文本
        elif obj.content_type == ChatLog.ContentType.VOICE:
            if obj.content_file_path:
                audio_url = settings.MEDIA_URL + obj.content_file_path
                return format_html(f'<a href="{audio_url}" target="_blank">语音文件</a> ({obj.voice_length}秒)')
            return f"[语音] ({obj.voice_length}秒)"
        elif obj.content_type == ChatLog.ContentType.IMAGE:
            if obj.content_file_path:
                img_url = settings.MEDIA_URL + obj.content_file_path
                return format_html(
                    '<a href="{0}" target="_blank"><img src="{0}" width="50" height="50" style="object-fit: cover;"/></a>',
                    img_url)
            return "[图片]"
        # 其他类型可以按需添加
        return obj.get_content_type_display()

    @admin.display(description='内容详情')
    def content_summary_detail(self, obj):
        """用于详情页的更详细的摘要，例如提供播放器"""
        if obj.content_type == ChatLog.ContentType.TEXT:
            return obj.content_text
        elif obj.content_type == ChatLog.ContentType.VOICE:
            if obj.content_file_path:
                audio_url = settings.MEDIA_URL + obj.content_file_path
                # 在Admin详情页嵌入一个HTML5音频播放器
                return format_html(
                    '<audio controls preload="none" style="width: 250px;">'
                    '<source src="{}" type="audio/amr">'
                    '您的浏览器不支持播放AMR格式音频。 <a href="{}">点击下载</a>'
                    '</audio><br>时长: {}秒',
                    audio_url, audio_url, obj.voice_length
                )
            return f"语音文件丢失 (时长: {obj.voice_length}秒)"
        return self.content_summary(obj)  # 复用简短摘要的逻辑

    # --- 权限控制 ---
    def has_add_permission(self, request):
        # 禁止在Admin中手动添加聊天记录
        return False

    def has_change_permission(self, request, obj=None):
        # 禁止在Admin中修改聊天记录
        return False

    def has_delete_permission(self, request, obj=None):
        # 允许删除记录，方便清理测试数据。如果不想允许删除，改为 return False
        return True


@admin.register(SmsMessage)
class SmsAdmin(admin.ModelAdmin):
    # 列表页显示哪些字段
    list_display = (
        'device', 'phone', 'message', 'error_cause', 'stamp')
