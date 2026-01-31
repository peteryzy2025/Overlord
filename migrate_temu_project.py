"""
TemuShop 模型修改迁移

如果 TemuShop 的 project 字段不允许 null，需要执行以下操作：

1. 修改模型 general/models.py：
   在 TemuShop 类中将 project 字段添加 null=True, blank=True

2. 创建迁移：
   python manage.py makemigrations general

3. 执行迁移：
   python manage.py migrate

如果不想修改模型，也可以在视图中设置默认项目：
"""

# 替代方案（不修改模型）：在视图中设置默认项目
"""
# 在保存时如果没有项目，设置为默认项目
from general.models import Project

def get_or_create_default_project(company):
    """获取或创建默认项目"""
    project, created = Project.objects.get_or_create(
        company=company,
        name='默认项目',
        defaults={
            'description': '系统自动创建的默认项目'
        }
    )
    return project

# 在创建/更新店铺时：project_id = data.get('project_id')
if project_id:
    try:
        project = Project.objects.get(id=project_id)
    except Project.DoesNotExist:
        project = get_or_create_default_project(request.user.company)
else:
    # 如果没有指定项目，设置为默认项目
    project = get_or_create_default_project(request.user.company)

shop.project = project
"""
