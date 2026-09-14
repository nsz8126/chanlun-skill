"""分析配置管理。"""

from __future__ import annotations

from chanlun import 缠论配置


# 默认周期组：1分钟 / 5分钟 / 30分钟 / 日线
DEFAULT_PERIODS = ["1m", "5m", "30m", "day"]


def default_config() -> 缠论配置:
    """默认分析配置：全量分析。
    
    包含60+个可配置字段，按功能分组：
    - 基础设置：标识
    - 缠K处理：缠K合并替换
    - 笔设置：笔内元素数量、笔内相同终点取舍、笔内起始分型包含整笔等
    - 线段设置：线段_非缺口下穿刺、线段_特征序列忽视老阴老阳等
    - 分析开关：分析笔、分析线段、分析扩展线段、分析笔中枢、分析线段中枢
    - 指标参数：MACD、RSI、KDJ、BOLL等
    - 买卖点设置：买卖点偏移、买卖点激进识别等
    - 背驰设置：线段内部背驰_MACD、线段内部背驰_斜率等
    """
    cfg = 缠论配置()
    
    # === 基础设置 ===
    cfg.标识 = "bar"
    
    # === 缠K处理 ===
    cfg.缠K合并替换 = False  # False: 在原缠K上合并, True: 产出新缠K
    
    # === 笔设置 ===
    cfg.笔内元素数量 = 5  # 成笔最低长度
    cfg.笔内相同终点取舍 = False  # True: last, False: first
    cfg.笔内起始分型包含整笔 = False  # True: 起始分型高低包含整支笔则不成笔
    cfg.笔内起始分型包含整笔_包括右 = False  # True: 将笔之武.右纳入
    cfg.笔内原始K线包含整笔 = False  # 判断原始K线包含整笔的情况
    cfg.笔次级成笔 = False
    cfg.笔弱化 = False
    cfg.笔弱化_原始数量 = 3
    
    # === 线段设置 ===
    cfg.线段_非缺口下穿刺 = False
    cfg.线段_特征序列忽视老阴老阳 = False  # True: 不用严格的特征序列包含
    cfg.线段_缺口后紧急修正 = True
    cfg.线段_修正 = False  # 短路修正，不建议使用
    cfg.线段内部中枢图显 = True
    cfg.扩展线段_当下分析 = False
    
    # === 分析开关 ===
    cfg.计算指标 = True
    cfg.分析笔 = True
    cfg.分析线段 = True
    cfg.分析扩展线段 = True
    cfg.分析笔中枢 = True
    cfg.分析线段中枢 = True
    
    # === 指标参数 ===
    cfg.指标计算方式 = "收"  # (开, 高, 低, 收, 高低均值, 高低收均值, 开高低收均值)
    
    # MACD参数
    cfg.平滑异同移动平均线_快线周期 = 12
    cfg.平滑异同移动平均线_慢线周期 = 26
    cfg.平滑异同移动平均线_信号周期 = 9
    
    # RSI参数
    cfg.相对强弱指数_周期 = 13
    cfg.相对强弱指数_移动平均线周期 = 13
    cfg.相对强弱指数_超买阈值 = 75.0
    cfg.相对强弱指数_超卖阈值 = 25.0
    
    # KDJ参数
    cfg.随机指标_RSV周期 = 13
    cfg.随机指标_K值平滑周期 = 5
    cfg.随机指标_D值平滑周期 = 5
    cfg.随机指标_超买阈值 = 80.0
    cfg.随机指标_超卖阈值 = 20.0
    
    # BOLL参数
    cfg.计算BOLL = False
    cfg.布林带_周期 = 20
    cfg.布林带_标准差倍数 = 2.0
    
    # 多参数指标列表
    cfg.均线_类型列表 = []
    cfg.均线_周期列表 = []
    cfg.MACD_参数列表 = []  # [(key, 快线, 慢线, 信号), ...]
    cfg.RSI_周期列表 = []  # [(key, 周期), ...]
    cfg.KDJ_参数列表 = []  # [(key, RSV周期, K平滑, D平滑), ...]
    cfg.BOLL_参数列表 = []  # [(key, 周期, 标准差倍数), ...]
    
    # === 推送/显示 ===
    cfg.图表展示 = False
    cfg.推送K线 = False
    cfg.推送笔 = False
    cfg.推送线段 = False
    cfg.推送中枢 = False
    cfg.图表展示_笔 = True
    cfg.图表展示_线段 = True
    cfg.图表展示_扩展线段 = True
    cfg.图表展示_扩展线段_线段 = True
    cfg.图表展示_线段_线段 = True
    cfg.图表展示_中枢_笔 = True
    cfg.图表展示_中枢_线段 = True
    cfg.图表展示_中枢_扩展线段 = True
    cfg.图表展示_中枢_扩展线段_线段 = True
    cfg.图表展示_中枢_线段_线段 = True
    cfg.图表展示_中枢_线段内部 = True
    
    # === 买卖点设置 ===
    cfg.买卖点偏移 = 1  # 最大偏移
    cfg.买卖点激进识别 = False  # 激进模式下将不考虑分型的完整性
    cfg.买卖点与MACD柱强相关 = False  # True: 卖点需正值 买点需负值
    cfg.买卖点错过误差值 = 0.01  # 距离买卖点值上下之内
    cfg.买卖点_指标模式 = "配置"  # 【任意，配置，全量, 相对】
    cfg.买卖点_指标匹配_MACD = True  # 买在负，卖在正！
    cfg.买卖点_指标匹配_KDJ = True  # 买在死叉之后，卖在金叉之后
    cfg.买卖点_指标匹配_RSI = True  # 买在均线之下，卖在均线之上
    
    # === 背驰设置 ===
    cfg.线段内部背驰_MACD = True
    cfg.线段内部背驰_斜率 = True
    cfg.线段内部背驰_测度 = True
    cfg.线段内部背驰_模式 = "相对"  # 【任意，配置，全量，相对】
    
    # === 其他 ===
    cfg.手动终止 = ""  # 如 "2099-12-31 00:00:00"
    cfg.加载文件路径 = ""
    
    return cfg


def minimal_config() -> 缠论配置:
    """轻量配置：仅笔和中枢，不计算指标。"""
    cfg = 缠论配置.不推送()
    cfg.计算指标 = False
    cfg.分析笔 = True
    cfg.分析线段 = False
    cfg.分析扩展线段 = False
    cfg.分析笔中枢 = True
    cfg.分析线段中枢 = False
    return cfg


def quiet_config() -> 缠论配置:
    """静默配置：关闭所有推送和图表。"""
    cfg = 缠论配置.不推送()
    cfg.计算指标 = True
    cfg.分析笔 = True
    cfg.分析线段 = True
    cfg.分析扩展线段 = True
    cfg.分析笔中枢 = True
    cfg.分析线段中枢 = True
    # MACD标准参数
    cfg.平滑异同移动平均线_快线周期 = 12
    cfg.平滑异同移动平均线_慢线周期 = 26
    cfg.平滑异同移动平均线_信号周期 = 9
    return cfg
