def get_user_permission_codes(user):
    """
    获取用户的所有权限code列表
    返回: list[int] - 如 [1, 2, 555] 或 []
    """
    if not user or not user.is_authenticated:
        return []

    # 直接从M2M表查询code列表（性能最优）
    return list(user.permission_configs.values_list('code', flat=True))