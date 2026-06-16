# ==============================================================================
# 电力交易辅助决策系统 - 爬虫优化框架 v51
# 功能：统一管理各数据源的爬取、解析、入库、监控
# ==============================================================================

import os
import sys
import time
import json
import logging
import requests
import pymysql
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps

# ==============================================================================
# 配置区
# ==============================================================================

# 数据库配置（根据你的实际情况修改）
DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'root',
    'password': '你的密码',
    'database': 'power_trading',
    'charset': 'utf8mb4',
    'autocommit': True
}

# 爬虫配置
CRAWLER_CONFIG = {
    'concurrent_workers': 3,        # 并发数（不建议太高）
    'retry_times': 5,               # 重试次数
    'retry_delay': 5,               # 重试延迟（秒）
    'timeout': 30,                  # 请求超时（秒）
    'sleep_between_requests': 2,    # 请求间隔（秒）
    'sleep_between_batches': 10,    # 批次间隔（秒）
}

# 目标站点配置
TARGET_SITES = {
    'henan_trading': {
        'name': '河南电力交易中心',
        'base_url': 'https://power.henan.gov.cn',  # 替换为实际地址
        'enabled': True,
    },
    'henan_grid': {
        'name': '河南电网',
        'base_url': 'https://www.hn.sgcc.com.cn',  # 替换为实际地址
        'enabled': True,
    },
}

# 请求头（模拟浏览器）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
}

# 可选代理列表（如果需要的话）
PROXIES = []  # 例如: ['http://proxy1.com:8080', 'http://proxy2.com:8080']

# ==============================================================================
# 日志系统
# ==============================================================================

def setup_logger():
    log_dir = '/data/crawler-v51/logs'
    os.makedirs(log_dir, exist_ok=True)
    
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = f'{log_dir}/crawler-{today}.log'
    error_file = f'{log_dir}/error-{today}.log'
    
    logger = logging.getLogger('PowerCrawler')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    # 控制台输出
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    
    # 运行日志
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    
    # 错误日志
    error_handler = logging.FileHandler(error_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    
    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    
    return logger

logger = setup_logger()

# ==============================================================================
# 数据库模块
# ==============================================================================

class DatabaseManager:
    def __init__(self):
        self.conn = None
        self.connect()
    
    def connect(self):
        try:
            self.conn = pymysql.connect(**DB_CONFIG)
            logger.info(f'✅ 数据库连接成功: {DB_CONFIG["host"]}')
        except Exception as e:
            logger.error(f'❌ 数据库连接失败: {e}')
            raise
    
    def close(self):
        if self.conn:
            self.conn.close()
            logger.info('数据库连接已关闭')
    
    def execute_query(self, sql, params=None):
        try:
            cursor = self.conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(sql, params or ())
            return cursor.fetchall()
        except Exception as e:
            logger.error(f'SQL执行失败: {sql[:100]}... 错误: {e}')
            raise
    
    def execute_insert(self, sql, params=None):
        try:
            cursor = self.conn.cursor()
            cursor.execute(sql, params or ())
            return cursor.rowcount
        except Exception as e:
            logger.error(f'插入失败: {sql[:100]}... 错误: {e}')
            raise
    
    def execute_many(self, sql, data_list):
        try:
            cursor = self.conn.cursor()
            cursor.executemany(sql, data_list)
            return cursor.rowcount
        except Exception as e:
            logger.error(f'批量插入失败: {sql[:100]}... 错误: {e}')
            raise

# ==============================================================================
# 重试机制装饰器
# ==============================================================================

def retry(max_retries=CRAWLER_CONFIG['retry_times'], delay=CRAWLER_CONFIG['retry_delay']):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                except Exception as e:
                    last_exception = e
                    wait_time = delay * attempt
                    logger.warning(f'⏳ 第 {attempt}/{max_retries} 次尝试失败: {func.__name__}, {e}')
                    logger.warning(f'   {wait_time}秒后重试...')
                    time.sleep(wait_time)
            
            logger.error(f'❌ 所有重试失败: {func.__name__}')
            raise last_exception if last_exception else Exception('重试失败')
        return wrapper
    return decorator

# ==============================================================================
# HTTP 请求模块
# ==============================================================================

class HttpClient:
    def __init__(self):
        self.proxy_index = 0
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
    def get_proxy(self):
        if not PROXIES:
            return None
        proxy = PROXIES[self.proxy_index % len(PROXIES)]
        self.proxy_index += 1
        return {'http': proxy, 'https': proxy}
    
    @retry(max_retries=5, delay=5)
    def get(self, url, params=None):
        proxy = self.get_proxy()
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=CRAWLER_CONFIG['timeout'],
                proxies=proxy
            )
            if response.status_code == 200:
                return response
            else:
                logger.warning(f'HTTP {response.status_code}: {url[:80]}')
                return None
        except requests.exceptions.Timeout:
            logger.warning(f'请求超时: {url[:80]}')
            return None
        except requests.exceptions.ConnectionError:
            logger.warning(f'连接失败: {url[:80]}')
            return None
        except Exception as e:
            logger.warning(f'请求异常: {e}')
            return None
    
    @retry(max_retries=5, delay=5)
    def post(self, url, data=None, json=None):
        proxy = self.get_proxy()
        try:
            response = self.session.post(
                url,
                data=data,
                json=json,
                timeout=CRAWLER_CONFIG['timeout'],
                proxies=proxy
            )
            if response.status_code == 200:
                return response
            else:
                logger.warning(f'HTTP {response.status_code}: {url[:80]}')
                return None
        except Exception as e:
            logger.warning(f'POST请求异常: {e}')
            return None

# ==============================================================================
# 基础爬虫类
# ==============================================================================

class BaseSpider:
    name = 'base'
    
    def __init__(self, db_manager, http_client):
        self.db = db_manager
        self.http = http_client
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'inserted': 0,
            'updated': 0,
            'skipped': 0,
        }
    
    def get_missing_dates(self, table_name, date_column='stat_date'):
        """
        检查数据库中缺失的日期，只爬取缺失的数据
        """
        today = datetime.now().date()
        start_date = today - timedelta(days=90)  # 检查最近90天
        
        try:
            sql = f"""
                SELECT DISTINCT DATE({date_column}) as d 
                FROM {table_name} 
                WHERE {date_column} >= %s
            """
            rows = self.db.execute_query(sql, (start_date,))
            existing_dates = set(row['d'] for row in rows)
            
            all_dates = set()
            current = start_date
            while current <= today:
                all_dates.add(current)
                current += timedelta(days=1)
            
            missing = sorted(all_dates - existing_dates)
            logger.info(f'[{self.name}] 需要补全 {len(missing)} 天的数据')
            if missing[:5]:
                logger.info(f'  缺失日期: {[d.strftime("%Y-%m-%d") for d in missing[:5]]}...')
            
            return missing
        except Exception as e:
            logger.error(f'检查缺失日期失败: {e}')
            # 如果检查失败，默认返回最近7天
            return [today - timedelta(days=i) for i in range(7)]
    
    def check_data_exists(self, table_name, conditions):
        """
        检查指定日期/时间段的数据是否已存在
        """
        where_clause = ' AND '.join([f'{k}=%s' for k in conditions.keys()])
        sql = f'SELECT COUNT(*) as cnt FROM {table_name} WHERE {where_clause}'
        try:
            result = self.db.execute_query(sql, tuple(conditions.values()))
            return result[0]['cnt'] > 0
        except Exception:
            return False
    
    def save_data(self, table_name, data_list, unique_keys=None):
        """
        智能保存数据：自动判断是插入还是更新
        """
        if not data_list:
            logger.info(f'[{self.name}] 无数据需要保存')
            return 0
        
        logger.info(f'[{self.name}] 准备保存 {len(data_list)} 条记录到 {table_name}')
        
        # 构造 SQL
        first_item = data_list[0]
        columns = list(first_item.keys())
        
        columns_str = ', '.join(columns)
        placeholders = ', '.join(['%s'] * len(columns))
        update_clause = ', '.join([f'{k}=VALUES({k})' for k in columns])
        
        sql = f'''
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_clause}
        '''
        
        # 批量处理
        batch_size = 500
        total_inserted = 0
        
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i+batch_size]
            try:
                params = [tuple(item[c] for c in columns) for item in batch]
                rows_affected = self.db.execute_many(sql, params)
                total_inserted += rows_affected
                logger.info(f'  ✓ 已保存 {len(batch)} 条 (批次 {i//batch_size + 1})')
            except Exception as e:
                logger.error(f'  ✗ 批次保存失败: {e}')
                # 尝试单条插入（定位问题）
                for item in batch:
                    try:
                        single_params = tuple(item[c] for c in columns)
                        self.db.execute_insert(sql, single_params)
                        total_inserted += 1
                    except Exception as e2:
                        logger.error(f'    单条插入也失败: {str(item)[:100]}, 错误: {e2}')
        
        self.stats['inserted'] = total_inserted
        logger.info(f'[{self.name}] {table_name} 保存完成: {total_inserted} 条')
        return total_inserted

# ==============================================================================
# 负荷信息爬虫（示例）
# ==============================================================================

class LoadInfoSpider(BaseSpider):
    name = 'load_info'
    
    def __init__(self, db_manager, http_client):
        super().__init__(db_manager, http_client)
    
    def crawl_date(self, date):
        """
        爬取指定日期的负荷信息
        
        【你需要在这里替换为你的实际爬取逻辑】
        参考字段: system_load, total_output, inter_provincial_tie, 
                  non_spot_output, renewable_output, hydro_output, pumped_output
        """
        logger.info(f'[{self.name}] 正在爬取: {date}')
        self.stats['total'] += 1
        
        try:
            # TODO: 替换为实际的爬取逻辑
            # 这是一个占位示例，你需要把实际爬虫代码整合进来
            date_str = date.strftime('%Y-%m-%d')
            
            # 示例：假设从 API 获取数据
            # url = f'https://power.henan.gov.cn/api/load-info?date={date_str}'
            # response = self.http.get(url)
            # if not response:
            #     self.stats['failed'] += 1
            #     return None
            # 
            # data = response.json()
            # records = self.parse_data(data, date)
            
            # ========== 这里插入你的实际爬取逻辑 ==========
            # 你的 v51 爬虫脚本中相关的代码应该放在这里
            # 
            # 例如：
            # records = []
            # for time_point in range(1, 97):  # 96个时间点
            #     record = {
            #         'stat_date': date_str,
            #         'time_id': time_point,
            #         'system_load': 系统负荷值,
            #         'total_output': 总出力值,
            #         ... 其他字段
            #     }
            #     records.append(record)
            # return records
            # =============================================
            
            self.stats['success'] += 1
            logger.info(f'[{self.name}] 爬取成功: {date}')
            return []  # 返回数据列表
            
        except Exception as e:
            logger.error(f'[{self.name}] 爬取失败 {date}: {e}')
            self.stats['failed'] += 1
            return None
    
    def run(self):
        """执行爬虫"""
        logger.info(f'========== {self.name} 爬虫开始 ==========')
        
        # 检查缺失日期
        missing_dates = self.get_missing_dates('load_info')
        
        if not missing_dates:
            logger.info(f'[{self.name}] 数据完整，无需爬取')
            return self.stats
        
        # 串行爬取（避免被封）
        all_data = []
        for date in missing_dates:
            records = self.crawl_date(date)
            if records:
                all_data.extend(records)
            time.sleep(CRAWLER_CONFIG['sleep_between_requests'])
        
        # 保存数据
        if all_data:
            self.save_data('load_info', all_data)
        
        logger.info(f'[{self.name}] 统计: 总 {self.stats["total"]} | 成功 {self.stats["success"]} | 失败 {self.stats["failed"]}')
        logger.info(f'========== {self.name} 爬虫结束 ==========')
        return self.stats

# ==============================================================================
# 电价数据爬虫（示例）
# ==============================================================================

class PriceSpider(BaseSpider):
    name = 'spot_clearing_price'
    
    def __init__(self, db_manager, http_client):
        super().__init__(db_manager, http_client)
    
    def crawl_date(self, date):
        """
        爬取指定日期的电价数据
        
        【你需要在这里替换为你的实际爬取逻辑】
        参考字段: price_central_east, price_south, price_west, price_north, price_user_side
        """
        logger.info(f'[{self.name}] 正在爬取: {date}')
        self.stats['total'] += 1
        
        try:
            date_str = date.strftime('%Y-%m-%d')
            
            # TODO: 实际爬取逻辑
            # url = f'https://power.henan.gov.cn/api/price?date={date_str}'
            # response = self.http.get(url)
            # ...
            
            self.stats['success'] += 1
            return []
            
        except Exception as e:
            logger.error(f'[{self.name}] 爬取失败 {date}: {e}')
            self.stats['failed'] += 1
            return None
    
    def run(self):
        logger.info(f'========== {self.name} 爬虫开始 ==========')
        missing_dates = self.get_missing_dates('spot_clearing_price')
        
        if not missing_dates:
            logger.info(f'[{self.name}] 数据完整，无需爬取')
            return self.stats
        
        all_data = []
        for date in missing_dates:
            records = self.crawl_date(date)
            if records:
                all_data.extend(records)
            time.sleep(CRAWLER_CONFIG['sleep_between_requests'])
        
        if all_data:
            self.save_data('spot_clearing_price', all_data)
        
        logger.info(f'[{self.name}] 统计: 总 {self.stats["total"]} | 成功 {self.stats["success"]} | 失败 {self.stats["failed"]}')
        logger.info(f'========== {self.name} 爬虫结束 ==========')
        return self.stats

# ==============================================================================
# 新能源出力爬虫（示例）
# ==============================================================================

class RenewableSpider(BaseSpider):
    name = 'renewable_generation'
    
    def __init__(self, db_manager, http_client):
        super().__init__(db_manager, http_client)
    
    def crawl_date(self, date):
        """
        爬取指定日期的新能源出力数据
        参考字段: wind_power, solar_power
        """
        logger.info(f'[{self.name}] 正在爬取: {date}')
        self.stats['total'] += 1
        
        try:
            date_str = date.strftime('%Y-%m-%d')
            # TODO: 实际爬取逻辑
            self.stats['success'] += 1
            return []
        except Exception as e:
            logger.error(f'[{self.name}] 爬取失败 {date}: {e}')
            self.stats['failed'] += 1
            return None
    
    def run(self):
        logger.info(f'========== {self.name} 爬虫开始 ==========')
        missing_dates = self.get_missing_dates('renewable_generation')
        
        if not missing_dates:
            logger.info(f'[{self.name}] 数据完整，无需爬取')
            return self.stats
        
        all_data = []
        for date in missing_dates:
            records = self.crawl_date(date)
            if records:
                all_data.extend(records)
            time.sleep(CRAWLER_CONFIG['sleep_between_requests'])
        
        if all_data:
            self.save_data('renewable_generation', all_data)
        
        logger.info(f'[{self.name}] 统计: 总 {self.stats["total"]} | 成功 {self.stats["success"]} | 失败 {self.stats["failed"]}')
        logger.info(f'========== {self.name} 爬虫结束 ==========')
        return self.stats

# ==============================================================================
# 断面约束数据爬虫（示例 - 大数据量）
# ==============================================================================

class SectionSpider(BaseSpider):
    name = 'section_data'
    
    def __init__(self, db_manager, http_client):
        super().__init__(db_manager, http_client)
    
    def crawl_date(self, date):
        """
        爬取断面约束数据（约620个断面 × 96时间点 = 59,520 条/天）
        """
        logger.info(f'[{self.name}] 正在爬取: {date} (大数据量)')
        self.stats['total'] += 1
        
        try:
            date_str = date.strftime('%Y-%m-%d')
            
            # TODO: 实际爬取逻辑
            # 这个表数据量很大（每天约6万条），需要特别优化
            # 建议使用批量插入，避免逐条写入
            
            self.stats['success'] += 1
            return []
        except Exception as e:
            logger.error(f'[{self.name}] 爬取失败 {date}: {e}')
            self.stats['failed'] += 1
            return None
    
    def run(self):
        logger.info(f'========== {self.name} 爬虫开始 ==========')
        missing_dates = self.get_missing_dates('section_data')
        
        if not missing_dates:
            logger.info(f'[{self.name}] 数据完整，无需爬取')
            return self.stats
        
        all_data = []
        for date in missing_dates:
            records = self.crawl_date(date)
            if records:
                all_data.extend(records)
            time.sleep(CRAWLER_CONFIG['sleep_between_requests'])
            
            # 数据量大时，分批保存
            if len(all_data) >= 50000:
                self.save_data('section_data', all_data)
                all_data = []
                logger.info(f'[{self.name}] 已保存一批，继续爬取...')
        
        if all_data:
            self.save_data('section_data', all_data)
        
        logger.info(f'[{self.name}] 统计: 总 {self.stats["total"]} | 成功 {self.stats["success"]} | 失败 {self.stats["failed"]}')
        logger.info(f'========== {self.name} 爬虫结束 ==========')
        return self.stats

# ==============================================================================
# 主调度器
# ==============================================================================

class CrawlerManager:
    def __init__(self):
        self.db = DatabaseManager()
        self.http = HttpClient()
        self.spiders = []
        self.all_stats = {}
    
    def register_spider(self, spider_class):
        spider = spider_class(self.db, self.http)
        self.spiders.append(spider)
        logger.info(f'已注册爬虫: {spider.name}')
    
    def run_all(self):
        """按顺序执行所有爬虫"""
        logger.info('=' * 60)
        logger.info('🚀 开始执行全部爬虫任务')
        logger.info('=' * 60)
        
        start_time = time.time()
        
        for spider in self.spiders:
            try:
                stats = spider.run()
                self.all_stats[spider.name] = stats
            except Exception as e:
                logger.error(f'❌ 爬虫 {spider.name} 执行异常: {e}')
                self.all_stats[spider.name] = {'error': str(e)}
            time.sleep(CRAWLER_CONFIG['sleep_between_batches'])
        
        # 输出总览
        elapsed = time.time() - start_time
        logger.info('=' * 60)
        logger.info(f'✅ 全部爬虫任务完成 (耗时 {elapsed:.1f} 秒)')
        logger.info('=' * 60)
        
        logger.info('\n📊 执行统计:')
        for name, stats in self.all_stats.items():
            if 'error' in stats:
                logger.info(f'  ❌ {name}: {stats["error"]}')
            else:
                logger.info(f'  ✅ {name}: 成功 {stats.get("success",0)}/{stats.get("total",0)} | 保存 {stats.get("inserted",0)} 条')
        
        self.db.close()
        return self.all_stats

# ==============================================================================
# 主入口
# ==============================================================================

def main():
    logger.info('\n' + '=' * 60)
    logger.info(f'⚡ 电力交易数据爬虫 v51')
    logger.info(f'🕐 启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    logger.info('=' * 60)
    
    # 初始化调度器
    manager = CrawlerManager()
    
    # 注册所有爬虫
    # manager.register_spider(LoadInfoSpider)
    # manager.register_spider(PriceSpider)
    # manager.register_spider(RenewableSpider)
    # manager.register_spider(SectionSpider)
    # ... 其他爬虫
    
    # 执行
    try:
        manager.run_all()
    except KeyboardInterrupt:
        logger.warning('\n⚠️ 用户中断执行')
        try:
            manager.db.close()
        except:
            pass
    except Exception as e:
        logger.error(f'\n❌ 执行出错: {e}')
        try:
            manager.db.close()
        except:
            pass

if __name__ == '__main__':
    main()
