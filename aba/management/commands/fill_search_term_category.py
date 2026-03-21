"""
填充搜索词的品类字段
根据 term 字段内容判断品类（shirt, hat, sticker 等）
"""
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from aba.models import SearchTerm


# 品类关键词映射（整词匹配）
CATEGORY_PATTERNS = {
    'sticker': ['sticker', 'stickers'],
    'banner': ['banner', 'banners'],
    'flag': ['flag', 'flags', 'garden flag'],
    'blanket': ['blanket', 'blankets'],
    'hat': ['hat', 'hats', 'baseball cap', 'snapback'],
    'shirt': ['shirt', 'shirts', 't-shirt', 'tshirt', 'tee'],
    'sock': ['sock', 'socks'],
    'apron': ['apron', 'aprons'],
    'badge': ['badge', 'badges', 'pin', 'pins'],
    'makeup bag': ['makeup bag', 'cosmetic bag'],
    'canvas bag': ['canvas bag', 'tote bag'],
    'sign': ['sign', 'signs', 'metal sign'],
    'tapestry': ['tapestry', 'tapestries', 'wall hanging'],
}


def detect_category(term):
    """根据搜索词判断品类（整词匹配，大小写不敏感）"""
    term_lower = term.lower()
    
    for category, keywords in CATEGORY_PATTERNS.items():
        for keyword in keywords:
            # 整词匹配
            pattern = rf'(^|[^a-z]){re.escape(keyword)}([^a-z]|$)'
            if re.search(pattern, term_lower):
                return category
    
    return ''  # 未匹配到


class Command(BaseCommand):
    help = '填充搜索词的品类字段'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='每批处理数量（默认1000）'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='试运行，不实际更新数据库'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        
        # 获取未填充品类的搜索词
        queryset = SearchTerm.objects.using('aba_db').filter(
            category=''
        ).order_by('id')
        
        total = queryset.count()
        self.stdout.write(f'找到 {total} 条未填充品类的搜索词')
        
        if dry_run:
            self.stdout.write('【试运行模式】不实际更新数据库')
        
        updated = 0
        batch = []
        
        for term_obj in queryset.iterator(chunk_size=batch_size):
            category = detect_category(term_obj.term)
            if category:
                term_obj.category = category
                batch.append(term_obj)
                
                if len(batch) >= batch_size:
                    if not dry_run:
                        with transaction.atomic(using='aba_db'):
                            SearchTerm.objects.using('aba_db').bulk_update(
                                batch, ['category']
                            )
                    updated += len(batch)
                    self.stdout.write(f'已更新 {updated} 条...')
                    batch = []
        
        # 处理剩余
        if batch:
            if not dry_run:
                with transaction.atomic(using='aba_db'):
                    SearchTerm.objects.using('aba_db').bulk_update(
                        batch, ['category']
                    )
            updated += len(batch)
        
        self.stdout.write(self.style.SUCCESS(
            f'完成！共更新 {updated} 条搜索词的品类字段'
        ))
