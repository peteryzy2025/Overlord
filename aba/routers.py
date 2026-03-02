"""
ABA 数据库路由配置
所有 aba app 的模型都使用 aba_db 数据库
"""


class ABA_Router:
    """
    ABA 数据路由：
    - 读操作：aba app -> aba_db
    - 写操作：aba app -> aba_db
    - 关系：允许 aba_db 内部的关系
    - 迁移：aba app 只迁移到 aba_db
    """

    def db_for_read(self, model, **hints):
        """读操作路由"""
        if model._meta.app_label == 'aba':
            return 'aba_db'
        return None

    def db_for_write(self, model, **hints):
        """写操作路由"""
        if model._meta.app_label == 'aba':
            return 'aba_db'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """允许的关系"""
        # 如果两个对象都来自 aba app，允许关系
        if obj1._meta.app_label == 'aba' and obj2._meta.app_label == 'aba':
            return True
        # 如果都不是 aba app，让其他路由器决定
        if obj1._meta.app_label != 'aba' and obj2._meta.app_label != 'aba':
            return None
        # 一个是 aba，一个不是，不允许关系
        return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """迁移路由"""
        if app_label == 'aba':
            # aba app 只迁移到 aba_db
            return db == 'aba_db'
        # 其他 app 只在 default 数据库迁移
        if db == 'aba_db':
            return False
        return None
