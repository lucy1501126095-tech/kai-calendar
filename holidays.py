"""中国法定假日数据 + 农历转换工具"""

from datetime import datetime

# 尝试导入zhdate，不可用时禁用农历功能
try:
    from zhdate import ZhDate
    HAS_ZHDATE = True
except ImportError:
    HAS_ZHDATE = False


def lunar_to_solar(year: int, month: int, day: int) -> tuple:
    """农历转阳历，返回 (year, month, day)"""
    if not HAS_ZHDATE:
        return None
    try:
        zh = ZhDate(year, month, day)
        dt = zh.to_datetime()
        return (dt.year, dt.month, dt.day)
    except Exception:
        return None


def get_lunar_anniversaries_for_year(anniversaries: list, year: int) -> list:
    """把农历纪念日转换为当年的阳历日期"""
    if not HAS_ZHDATE:
        return []
    results = []
    for a in anniversaries:
        if not a.get('is_lunar'):
            continue
        solar = lunar_to_solar(year, a['month'], a['day'])
        if solar:
            results.append({
                'id': a['id'],
                'name': a['name'],
                'lunar': f"农历{a['month']}月{a['day']}日",
                'solar_date': f"{solar[0]:04d}-{solar[1]:02d}-{solar[2]:02d}",
                'month': solar[1],
                'day': solar[2],
            })
    return results


# 中国法定假日数据
# 每年更新一次，格式: (月, 日, 名称)
# 固定假日（每年不变的日期）
FIXED_HOLIDAYS = [
    (1, 1, "元旦"),
    (5, 1, "劳动节"),
    (10, 1, "国庆节"),
    (10, 2, "国庆节"),
    (10, 3, "国庆节"),
]

# 农历假日 (农历月, 农历日, 名称)
LUNAR_HOLIDAYS = [
    (1, 1, "春节"),
    (1, 2, "春节"),
    (1, 3, "春节"),
    (5, 5, "端午节"),
    (8, 15, "中秋节"),
]

# 特殊假日（需要查表的，比如清明节在4月4或5日）
# 清明节一般在4月4日或4月5日
QINGMING_DATES = {
    2025: (4, 4), 2026: (4, 5), 2027: (4, 5), 2028: (4, 4),
    2029: (4, 4), 2030: (4, 5), 2031: (4, 5), 2032: (4, 4),
    2033: (4, 4), 2034: (4, 5), 2035: (4, 5),
}


def generate_holidays_for_year(year: int) -> list:
    """生成指定年份的所有法定假日"""
    holidays = []

    # 固定假日
    for m, d, name in FIXED_HOLIDAYS:
        holidays.append({
            'year': year,
            'name': name,
            'date': f"{year:04d}-{m:02d}-{d:02d}",
            'holiday_type': 'holiday',
        })

    # 清明节
    qm = QINGMING_DATES.get(year, (4, 5))
    holidays.append({
        'year': year,
        'name': '清明节',
        'date': f"{year:04d}-{qm[0]:02d}-{qm[1]:02d}",
        'holiday_type': 'holiday',
    })

    # 农历假日
    if HAS_ZHDATE:
        for lm, ld, name in LUNAR_HOLIDAYS:
            solar = lunar_to_solar(year, lm, ld)
            if solar:
                holidays.append({
                    'year': year,
                    'name': name,
                    'date': f"{solar[0]:04d}-{solar[1]:02d}-{solar[2]:02d}",
                    'holiday_type': 'holiday',
                })

    return holidays
