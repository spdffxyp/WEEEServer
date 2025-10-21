"""
URL configuration for WEEEServer project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from teemog1_api import views as teemog1_api_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # Teemo G1 URL
    path('', include('teemog1_api.urls')),
    # 捕获所有其他未匹配的URL
    # re_path(r'^(?P<path>.*)$', teemog1_api_views.catch_all),
]

# 这段代码的作用是：当项目处于 DEBUG 模式时，
# 自动添加一个 URL 规则，将所有以 MEDIA_URL 开头的请求
# 路由到 MEDIA_ROOT 目录下的静态文件服务。
# 这在生产环境中是不推荐的，生产环境应由 Nginx 或 Apache 等 Web 服务器直接处理媒体文件。
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# 捕获所有其他未匹配的URL
urlpatterns.append(re_path(r'^(?P<path>.*)$', teemog1_api_views.catch_all))
