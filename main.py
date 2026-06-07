import os
import json
from datetime import datetime

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import llm_tool, logger

from .database import CalendarDB
from .holidays import generate_holidays_for_year, get_lunar_anniversaries_for_year, HAS_ZHDATE
from .backup import BackupManager


@register("kai_calendar", "Kai", "Kai的日历系统 - 经期追踪、用药打卡、纪念日、身体备注、待办提醒", "1.0.0")
class KaiCalendar(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        data_dir = os.path.join(context.get_data_dir(), "kai_calendar")
        os.makedirs(data_dir, exist_ok=True)
        self.db = CalendarDB(os.path.join(data_dir, "calendar.db"))
        self.backup_mgr = BackupManager(
            db_path=os.path.join(data_dir, "calendar.db"),
            backup_dir=os.path.join(data_dir, "backups"),
            max_backups=4,
        )

    async def initialize(self):
        """插件初始化：加载假日数据，预存纪念日"""
        year = datetime.now().year
        self._load_holidays(year)
        self._load_holidays(year + 1)
        self._init_default_anniversaries()
        logger.info("kai_calendar 初始化完成")

    def _load_holidays(self, year: int):
        holidays = generate_holidays_for_year(year)
        for h in holidays:
            self.db.add_holiday(h['year'], h['name'], h['date'], h['holiday_type'])

    def _init_default_anniversaries(self):
        existing = self.db.get_all_anniversaries()
        if existing:
            return
        defaults = [
            ("初遇纪念日", 12, 14, 0, 1, None, "奶茶店见面"),
            ("求婚纪念日", 12, 19, 0, 1, None, None),
            ("结婚纪念日", 12, 25, 0, 1, None, "小熊蛋糕"),
            ("每月14号", 0, 14, 0, 1, None, "月纪念日"),
            ("宝宝生日", 11, 20, 1, 1, None, "农历十一月二十"),
        ]
        for name, m, d, lunar, recur, yr, notes in defaults:
            if m == 0:
                for month in range(1, 13):
                    self.db.add_anniversary(f"{month}月14日纪念日", month, d, lunar, recur, yr, notes)
            else:
                self.db.add_anniversary(name, m, d, lunar, recur, yr, notes)

    # ==================== 经期追踪工具 ====================

    @llm_tool(name="cal_period_record")
    async def cal_period_record(self, event: AstrMessageEvent,
                                 action: str, date: str,
                                 is_natural: str = "false",
                                 notes: str = ""):
        """记录经期相关信息。用于记录黄体酮开始服用、停药、来经、经期结束。

        Args:
            action(string): 操作类型。可选值：progesterone_start(开始吃黄体酮)、progesterone_stop(黄体酮停药)、period_start(来经了)、period_end(经期结束)
            date(string): 日期，格式YYYY-MM-DD
            is_natural(string): 是否自然来经（不是黄体酮催的），true或false，默认false
            notes(string): 备注信息，可选
        """
        latest = self.db.get_latest_period()
        natural = is_natural.lower() == "true"

        if action == "progesterone_start":
            pid = self.db.add_period(progesterone_start=date, notes=notes or None)
            return f"已记录黄体酮开始服用，日期{date}，记录ID:{pid}"

        elif action == "progesterone_stop":
            if latest and latest['progesterone_start'] and not latest['progesterone_stop']:
                self.db.update_period(latest['id'], progesterone_stop=date)
                start = datetime.strptime(latest['progesterone_start'], '%Y-%m-%d')
                stop = datetime.strptime(date, '%Y-%m-%d')
                days = (stop - start).days
                return f"已记录黄体酮停药，日期{date}，本次服用{days}天。现在开始关注停药后的身体反应。"
            else:
                pid = self.db.add_period(progesterone_stop=date, notes=notes or None)
                return f"已记录黄体酮停药，日期{date}，记录ID:{pid}"

        elif action == "period_start":
            if latest and not latest['period_start']:
                self.db.update_period(latest['id'], period_start=date,
                                       is_natural=1 if natural else 0)
                resp_days = None
                if latest.get('progesterone_stop'):
                    stop = datetime.strptime(latest['progesterone_stop'], '%Y-%m-%d')
                    start = datetime.strptime(date, '%Y-%m-%d')
                    resp_days = (start - stop).days
                msg = f"已记录来经，日期{date}"
                if natural:
                    msg += "（自然来经！）"
                if resp_days is not None:
                    msg += f"，停药后第{resp_days}天来经"
                return msg
            else:
                pid = self.db.add_period(period_start=date,
                                          is_natural=1 if natural else 0,
                                          notes=notes or None)
                msg = f"已记录来经，日期{date}，记录ID:{pid}"
                if natural:
                    msg += "（自然来经！）"
                return msg

        elif action == "period_end":
            if latest and latest['period_start'] and not latest['period_end']:
                self.db.update_period(latest['id'], period_end=date)
                start = datetime.strptime(latest['period_start'], '%Y-%m-%d')
                end = datetime.strptime(date, '%Y-%m-%d')
                duration = (end - start).days
                return f"已记录经期结束，日期{date}，本次经期持续{duration}天"
            else:
                return "没有找到对应的经期开始记录，请先记录来经日期。"

        return f"未知操作:{action}"

    @llm_tool(name="cal_period_query")
    async def cal_period_query(self, event: AstrMessageEvent,
                                query_type: str = "latest"):
        """查询经期记录和趋势。

        Args:
            query_type(string): 查询类型。latest(最近一条记录)、history(近10条历史)、trends(趋势分析)
        """
        if query_type == "latest":
            p = self.db.get_latest_period()
            if not p:
                return "暂无经期记录。"
            return json.dumps(p, ensure_ascii=False)

        elif query_type == "history":
            periods = self.db.get_periods(10)
            if not periods:
                return "暂无经期记录。"
            return json.dumps(periods, ensure_ascii=False)

        elif query_type == "trends":
            trends = self.db.get_period_trends()
            return json.dumps(trends, ensure_ascii=False)

        return "未知查询类型"

    # ==================== 用药打卡工具 ====================

    @llm_tool(name="cal_medication")
    async def cal_medication(self, event: AstrMessageEvent,
                              date: str,
                              inositol: str = "",
                              magnesium: str = "",
                              k2: str = "",
                              progesterone: str = "",
                              notes: str = ""):
        """记录用药打卡。记录宝宝当天吃了哪些补剂/药物。

        Args:
            date(string): 日期，格式YYYY-MM-DD
            inositol(string): 肌醇是否服用，true/false，不填则不更新
            magnesium(string): 镁片是否服用，true/false，不填则不更新
            k2(string): K2是否服用，true/false，不填则不更新
            progesterone(string): 黄体酮是否服用，true/false，不填则不更新
            notes(string): 备注，可选
        """
        kwargs = {}
        if inositol:
            kwargs['inositol'] = 1 if inositol.lower() == 'true' else 0
        if magnesium:
            kwargs['magnesium'] = 1 if magnesium.lower() == 'true' else 0
        if k2:
            kwargs['k2'] = 1 if k2.lower() == 'true' else 0
        if progesterone:
            kwargs['progesterone'] = 1 if progesterone.lower() == 'true' else 0
        if notes:
            kwargs['notes'] = notes

        self.db.record_medication(date, **kwargs)

        streak = self.db.calculate_streak('all')
        taken = []
        skipped = []
        for name, key in [('肌醇', 'inositol'), ('镁片', 'magnesium'),
                           ('K2', 'k2'), ('黄体酮', 'progesterone')]:
            if key in kwargs:
                if kwargs[key]:
                    taken.append(name)
                else:
                    skipped.append(name)

        msg = f"已记录{date}用药："
        if taken:
            msg += f"服用了{'、'.join(taken)}"
        if skipped:
            msg += f"，未服用{'、'.join(skipped)}"
        msg += f"。当前连续打卡{streak['current']}天"
        if streak['best_days'] > streak['current']:
            msg += f"（历史最佳：{streak['best_days']}天，{streak['best_start']}~{streak['best_end']}）"
        return msg

    @llm_tool(name="cal_medication_query")
    async def cal_medication_query(self, event: AstrMessageEvent,
                                    query_type: str = "today",
                                    days: str = "7"):
        """查询用药记录和streak。

        Args:
            query_type(string): 查询类型。today(今天记录)、history(历史记录)、streak(连续打卡)、missing(缺失天数)
            days(string): 查询历史天数，默认7天
        """
        if query_type == "today":
            today = datetime.now().strftime('%Y-%m-%d')
            med = self.db.get_medication(today)
            if not med:
                return f"今天({today})还没有用药记录。"
            return json.dumps(med, ensure_ascii=False)

        elif query_type == "history":
            history = self.db.get_medication_history(int(days))
            if not history:
                return f"最近{days}天没有用药记录。"
            return json.dumps(history, ensure_ascii=False)

        elif query_type == "streak":
            streak = self.db.calculate_streak('all')
            return json.dumps(streak, ensure_ascii=False)

        elif query_type == "missing":
            missing = self.db.get_med_missing_days()
            return f"距离上次用药记录已过{missing}天"

        return "未知查询类型"

    # ==================== 身体备注工具 ====================

    @llm_tool(name="cal_body_note")
    async def cal_body_note(self, event: AstrMessageEvent,
                             action: str, content: str = "",
                             tags: str = "", days: str = "7"):
        """记录或查询身体状况备注。用于记录肚子疼、情绪波动、出血量等身体状况。

        Args:
            action(string): 操作类型。add(添加备注)、query(查询备注)
            content(string): 备注内容，添加时必填
            tags(string): 标签，用逗号分隔，如"腹痛,情绪波动"，可选
            days(string): 查询时的天数范围，默认7天
        """
        if action == "add":
            if not content:
                return "请提供备注内容"
            nid = self.db.add_body_note(content, tags)
            return f"已记录身体备注：{content}" + (f"（标签：{tags}）" if tags else "")

        elif action == "query":
            notes = self.db.get_body_notes(int(days))
            if not notes:
                return f"最近{days}天没有身体备注。"
            return json.dumps(notes, ensure_ascii=False)

        return "未知操作"

    # ==================== 纪念日工具 ====================

    @llm_tool(name="cal_anniversary")
    async def cal_anniversary(self, event: AstrMessageEvent,
                               action: str, name: str = "",
                               month: str = "", day: str = "",
                               is_lunar: str = "false",
                               anniversary_id: str = "",
                               notes: str = ""):
        """管理纪念日。支持添加、删除、修改、查询纪念日。支持农历。

        Args:
            action(string): 操作类型。add(添加)、delete(删除)、update(修改)、list(列表)
            name(string): 纪念日名称，添加/修改时使用
            month(string): 月份数字，添加时使用
            day(string): 日期数字，添加时使用
            is_lunar(string): 是否农历，true或false，默认false
            anniversary_id(string): 纪念日ID，删除/修改时使用
            notes(string): 备注，可选
        """
        if action == "add":
            if not name or not month or not day:
                return "添加纪念日需要名称、月份和日期"
            lunar = 1 if is_lunar.lower() == "true" else 0
            aid = self.db.add_anniversary(name, int(month), int(day),
                                           lunar, 1, None, notes or None)
            lunar_str = "（农历）" if lunar else ""
            return f"已添加纪念日：{name}，{month}月{day}日{lunar_str}，ID:{aid}"

        elif action == "delete":
            if not anniversary_id:
                return "删除需要提供纪念日ID"
            self.db.delete_anniversary(int(anniversary_id))
            return f"已删除纪念日ID:{anniversary_id}"

        elif action == "update":
            if not anniversary_id:
                return "修改需要提供纪念日ID"
            kwargs = {}
            if name:
                kwargs['name'] = name
            if month:
                kwargs['month'] = int(month)
            if day:
                kwargs['day'] = int(day)
            if notes:
                kwargs['notes'] = notes
            self.db.update_anniversary(int(anniversary_id), **kwargs)
            return f"已更新纪念日ID:{anniversary_id}"

        elif action == "list":
            annivs = self.db.get_all_anniversaries()
            if HAS_ZHDATE:
                year = datetime.now().year
                lunar_solar = get_lunar_anniversaries_for_year(annivs, year)
                for ls in lunar_solar:
                    for a in annivs:
                        if a['id'] == ls['id']:
                            a['solar_this_year'] = ls['solar_date']
            if not annivs:
                return "暂无纪念日记录。"
            return json.dumps(annivs, ensure_ascii=False)

        return "未知操作"

    # ==================== Kai备注工具 ====================

    @llm_tool(name="cal_kai_note")
    async def cal_kai_note(self, event: AstrMessageEvent,
                            action: str, content: str = "",
                            limit: str = "20"):
        """Kai的私人备注本。Kai自己写入的观察和记录，宝宝不问就不说。

        Args:
            action(string): 操作类型。write(写入备注)、read(读取备注)
            content(string): 备注内容，写入时使用
            limit(string): 读取条数，默认20
        """
        if action == "write":
            if not content:
                return "没有内容可写"
            nid = self.db.add_kai_note(content)
            return f"备注已记录，ID:{nid}"

        elif action == "read":
            notes = self.db.get_kai_notes(int(limit))
            if not notes:
                return "暂无备注。"
            return json.dumps(notes, ensure_ascii=False)

        return "未知操作"

    # ==================== 待办工具 ====================

    @llm_tool(name="cal_todo")
    async def cal_todo(self, event: AstrMessageEvent,
                        action: str, content: str = "",
                        due_date: str = "", todo_id: str = ""):
        """管理待办事项。宝宝随口提到的事情可以记下来，到时候提醒。

        Args:
            action(string): 操作类型。add(添加)、complete(完成)、delete(删除)、list(列表)
            content(string): 待办内容，添加时使用
            due_date(string): 截止日期YYYY-MM-DD，添加时使用，可选
            todo_id(string): 待办ID，完成/删除时使用
        """
        if action == "add":
            if not content:
                return "请提供待办内容"
            tid = self.db.add_todo(content, due_date or None)
            msg = f"已添加待办：{content}，ID:{tid}"
            if due_date:
                msg += f"，截止日期{due_date}"
            return msg

        elif action == "complete":
            if not todo_id:
                return "完成待办需要提供ID"
            self.db.complete_todo(int(todo_id))
            return f"待办ID:{todo_id}已完成"

        elif action == "delete":
            if not todo_id:
                return "删除待办需要提供ID"
            self.db.delete_todo(int(todo_id))
            return f"待办ID:{todo_id}已删除"

        elif action == "list":
            todos = self.db.get_pending_todos()
            if not todos:
                return "没有未完成的待办。"
            return json.dumps(todos, ensure_ascii=False)

        return "未知操作"

    # ==================== 假日查询工具 ====================

    @llm_tool(name="cal_holidays")
    async def cal_holidays(self, event: AstrMessageEvent,
                            query_type: str = "upcoming",
                            days: str = "30"):
        """查询中国法定假日。

        Args:
            query_type(string): 查询类型。upcoming(即将到来的假日)、year(全年假日)
            days(string): upcoming模式下查询未来多少天，默认30
        """
        if query_type == "upcoming":
            holidays = self.db.get_upcoming_holidays(int(days))
            if not holidays:
                return f"未来{days}天没有法定假日。"
            return json.dumps(holidays, ensure_ascii=False)

        elif query_type == "year":
            year = datetime.now().year
            holidays = self.db.get_holidays(year)
            if not holidays:
                return f"{year}年暂无假日数据。"
            return json.dumps(holidays, ensure_ascii=False)

        return "未知查询类型"

    # ==================== 每日检查（供主动消息调用） ====================

    @llm_tool(name="cal_daily_check")
    async def cal_daily_check(self, event: AstrMessageEvent):
        """执行每日检查，返回所有需要关注的事项：纪念日、假日、用药缺失、待办到期、黄体酮状态。

        Args:
        """
        alerts = self.db.check_daily()

        # 补充农历纪念日检查
        if HAS_ZHDATE:
            today = datetime.now()
            annivs = self.db.get_all_anniversaries()
            lunar_this_year = get_lunar_anniversaries_for_year(annivs, today.year)
            for la in lunar_this_year:
                solar_date = datetime.strptime(la['solar_date'], '%Y-%m-%d')
                diff = (solar_date - today).days
                if 0 <= diff <= 3:
                    alerts['anniversaries'].append({
                        'name': la['name'],
                        'date': la['solar_date'],
                        'lunar': la['lunar'],
                        'days_until': diff,
                    })

        return json.dumps(alerts, ensure_ascii=False)

    # ==================== 备份工具 ====================

    @llm_tool(name="cal_backup")
    async def cal_backup(self, event: AstrMessageEvent,
                          action: str = "create"):
        """管理日历数据备份。

        Args:
            action(string): 操作类型。create(创建备份)、list(列出备份)
        """
        if action == "create":
            path = self.backup_mgr.create_backup("manual")
            return f"备份已创建：{os.path.basename(path)}"

        elif action == "list":
            backups = self.backup_mgr.list_backups()
            if not backups:
                return "暂无备份文件。"
            return json.dumps(backups, ensure_ascii=False)

        return "未知操作"

    # ==================== 指令（手动触发） ====================

    @filter.command("cal_backup")
    async def cmd_backup(self, event: AstrMessageEvent):
        """手动触发数据备份"""
        path = self.backup_mgr.create_backup("manual")
        yield event.plain_result(f"日历数据已备份：{os.path.basename(path)}")

    @filter.command("cal_status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看日历系统状态"""
        annivs = self.db.get_all_anniversaries()
        periods = self.db.get_periods(1)
        streak = self.db.calculate_streak('all')
        todos = self.db.get_pending_todos()
        backups = self.backup_mgr.list_backups()

        msg = (
            f"📅 kai_calendar 状态\n"
            f"纪念日: {len(annivs)}个\n"
            f"经期记录: {'有' if periods else '无'}\n"
            f"用药streak: 当前{streak['current']}天 / 最佳{streak['best_days']}天\n"
            f"待办: {len(todos)}个未完成\n"
            f"备份: {len(backups)}份\n"
            f"农历支持: {'✓' if HAS_ZHDATE else '✗ (需安装zhdate)'}"
        )
        yield event.plain_result(msg)

    async def terminate(self):
        """插件卸载前备份一次"""
        try:
            self.backup_mgr.create_backup("shutdown")
        except Exception as e:
            logger.warning(f"关闭备份失败: {e}")
