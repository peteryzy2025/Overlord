# -*- coding: utf-8 -*-
"""
Divi 应用 URL 配置
"""
from django.urls import path
from . import views

urlpatterns = [
    path('api/divi/sync-templates/', views.sync_templates_api, name='sync_templates'),
]
