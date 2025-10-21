from django.urls import path
from . import views

urlpatterns = [
    path('timo/apps/get.do', views.get_apps, name='get_apps'),
    path('theme/package/info.do', views.get_theme_info, name='get_theme_info'),
    path('dial/package/info.do', views.get_dial_info, name='get_dial_info'),
    path('timo/version/get.do', views.get_version, name='get_version'),
    path('commoncontact/e1/add.do', views.add_contact, name='add_contact'),
    path('commoncontact/e1/update.do', views.update_contact, name='update_contact'),
    path('commoncontact/e1/del.do', views.delete_contact, name='delete_contact'),
    path('emoticon/package/info.do', views.get_emoticon_package_info, name='get_emoticon_package_info'),
    path('chat/image/upload.do', views.chat_image_upload, name='chat_image_upload'),
]
