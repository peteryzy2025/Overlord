import time

class Timer:
    def __init__(self):
        self._start = None
        self._end = None

    def start(self):
        """记录开始时间"""
        self._start = time.perf_counter()
        self._end = None  # 重置结束时间
        return self

    def stop(self):
        """记录结束时间"""
        if self._start is None:
            raise RuntimeError("Timer 未启动，请先调用 .start()")
        self._end = time.perf_counter()
        return self

    def elapsed(self):
        """返回耗时（秒）"""
        if self._start is None:
            raise RuntimeError("Timer 未启动，请先调用 .start()")
        if self._end is None:
            # 如果未调用 stop，则计算到当前时间
            return time.perf_counter() - self._start
        return self._end - self._start

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        print(self)

    def __str__(self):
        total_seconds = self.elapsed()
        return self._format_time(total_seconds)

    @staticmethod
    def _format_time(seconds):
        """将秒格式化为易读字符串"""
        seconds = round(seconds, 2)
        if seconds < 60:
            return f"{seconds}秒"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60:
            return f"{int(minutes)}分{int(sec)}秒"
        hours, minutes = divmod(minutes, 60)
        if hours < 24:
            return f"{int(hours)}小时{int(minutes)}分{int(sec)}秒"
        days, hours = divmod(hours, 24)
        return f"{int(days)}天{int(hours)}小时{int(minutes)}分{int(sec)}秒"

# ====== 使用示例 ======
if __name__ == "__main__":
    # 方法1：手动控制
    t = Timer()
    t.start()
    time.sleep(2.5)
    t.stop()
    print("耗时：", t)
