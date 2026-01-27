from django.db import migrations
from django.db.models import Q

def migrate_permissions(apps, schema_editor):
    User = apps.get_model('general', 'User')
    PermissionConfig = apps.get_model('general', 'PermissionConfig')

    # 创建权限配置（如果尚未存在）
    permissions = [
        {'code': 123, 'name': '查看店铺', 'description': '允许查看店铺列表'},
        {'code': 546, 'name': '删除订单', 'description': '允许删除订单记录'},
        {'code': 555, 'name': '管理组目标', 'description': '允许创建/编辑组绩效目标'}
    ]

    for perm in permissions:
        PermissionConfig.objects.get_or_create(code=perm['code'], defaults=perm)

    # 迁移用户权限
    for user in User.objects.all():
        if user.permission:
            perm_codes = [int(code) for code in user.permission.split(',') if code.isdigit()]
            perm_objs = PermissionConfig.objects.filter(code__in=perm_codes)
            user.permission_configs.set(perm_objs)

class Migration(migrations.Migration):
    dependencies = [
        ('general', '0001_initial'),  # 替换为你的实际依赖
    ]

    operations = [
        migrations.RunPython(migrate_permissions),
    ]