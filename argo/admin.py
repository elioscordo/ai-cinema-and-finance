from django import forms
from django.db import models
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.decorators import action
from simple_history.admin import SimpleHistoryAdmin
from agent.admin_utils import AjaxTaskModelAdmin, ModelActionsAdminMixin
from agent.sections import AjaxSectionAdminMixin, MessageHistorySection

from .models import (
    Account,
    Position,
    Strategy,
    Portfolio,
    StrategyInstance,
    StrategyInstrument,
    Backtest,
    BacktestRun,
    HistoricalData,
    Scanner,
    Signal,
    Recommendation,
    InstrumentGroup,
    Instrument,
)
from .sections import StrategyCodeSection, BacktestRunSection, RunSection
from .utils import load_strategies_from_package


@admin.register(Account)
class AccountAdmin(ModelAdmin):
    list_display = ('account_id', 'account_type', 'base_currency', 'balance_total', 'balance_free', 'balance_locked', 'is_reported', 'updated_at')
    list_filter = ('account_type', 'base_currency', 'is_reported')
    search_fields = ('account_id', 'account_type', 'base_currency')
    readonly_fields = ('updated_at',)


@admin.register(Position)
class PositionAdmin(ModelAdmin):
    list_display = ('account_id', 'instrument_id', 'side', 'status', 'quantity', 'avg_price', 'realized_pnl', 'unrealized_pnl', 'updated_at')
    list_filter = ('side', 'status')
    search_fields = ('account_id', 'instrument_id')
    readonly_fields = ('updated_at',)


@admin.register(Strategy)
class StrategyAdmin(AjaxSectionAdminMixin, ModelAdmin):
    list_display = ('name', 'class_path', 'description')
    search_fields = ('name', 'class_path')
    actions_list = ['load_strategies_from_package_action']
    list_sections = [StrategyCodeSection]
    changeform_sections = [StrategyCodeSection]

    @action(description=_("Load Strategies from Package"), icon="sync")
    def load_strategies_from_package_action(self, request):
        loaded = load_strategies_from_package("argo.strategies")
        self.message_user(
            request,
            _("Successfully loaded/synced %(count)d strategies from argo.strategies.") % {"count": len(loaded)}
        )
        return redirect(reverse("admin:argo_strategy_changelist"))


class StrategyInstanceInline(StackedInline):
    model = StrategyInstance
    extra = 0
    autocomplete_fields = ('strategy_model',)


@admin.register(Portfolio)
class PortfolioAdmin(SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('name', 'is_active', 'instance_count', 'group_count', 'description', 'last_tasks')
    list_filter = ('is_active', 'instrument_groups')
    search_fields = ('name', 'description')
    autocomplete_fields = ('instrument_groups',)
    list_sections = [MessageHistorySection]
    list_refresh = ['instance_count', 'group_count']
    inlines = []

    def instance_count(self, obj):
        if hasattr(obj, 'strategy_instances'):
            return obj.strategy_instances.count()
        return 0
    instance_count.short_description = _("Instances")

    def group_count(self, obj):
        return obj.instrument_groups.count()
    group_count.short_description = _("Groups")




class StrategyInstrumentInline(TabularInline):
    model = StrategyInstrument
    extra = 1
    autocomplete_fields = ('instrument',)
    fields = ('key', 'instrument')


@admin.register(StrategyInstrument)
class StrategyInstrumentAdmin(ModelAdmin):
    list_display = ('strategy_instance', 'key', 'instrument', 'created_at')
    list_filter = ('key', 'instrument__symbol')
    search_fields = ('key', 'instrument__symbol')
    autocomplete_fields = ('strategy_instance', 'instrument')


def format_float_precision(val: float | None, max_digits: int = 4) -> str:
    """Formats float values with at most `max_digits` decimal places, omitting redundant trailing zeros."""
    if val is None:
        return "-"
    try:
        f_val = float(val)
    except (ValueError, TypeError):
        return str(val)
    formatted = f"{f_val:.{max_digits}f}".rstrip("0").rstrip(".")
    return formatted if formatted and formatted not in ("-", "-0") else "0"


class BacktestFloatDisplayMixin:
    """
    Mixin ensuring all float performance metrics are displayed with at most 4 decimal
    precision across list_display, readonly_fields, and tabular inlines.
    """

    @admin.display(description=_("Return %"), ordering="return_pct")
    def return_pct(self, obj):
        return format_float_precision(obj.return_pct)

    @admin.display(description=_("Sharpe"), ordering="sharpe_ratio")
    def sharpe_ratio(self, obj):
        return format_float_precision(obj.sharpe_ratio)

    @admin.display(description=_("Sortino"), ordering="sortino_ratio")
    def sortino_ratio(self, obj):
        return format_float_precision(obj.sortino_ratio)

    @admin.display(description=_("Calmar"), ordering="calmar_ratio")
    def calmar_ratio(self, obj):
        return format_float_precision(obj.calmar_ratio)

    @admin.display(description=_("Max DD %"), ordering="max_drawdown_pct")
    def max_drawdown_pct(self, obj):
        return format_float_precision(obj.max_drawdown_pct)

    @admin.display(description=_("Profit Factor"), ordering="profit_factor")
    def profit_factor(self, obj):
        return format_float_precision(obj.profit_factor)

    @admin.display(description=_("Win Rate"), ordering="win_rate")
    def win_rate(self, obj):
        return format_float_precision(obj.win_rate)

    @admin.display(description=_("Commission Rate"), ordering="commission_rate")
    def commission_rate(self, obj):
        return format_float_precision(getattr(obj, "commission_rate", None))


class BacktestInline(BacktestFloatDisplayMixin, TabularInline):
    model = Backtest
    extra = 0
    fields = ('name', 'start_date', 'end_date', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'total_trades', 'last_tasks')
    readonly_fields = ('total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'total_trades', 'last_tasks')
    show_change_link = True


@admin.register(StrategyInstance)
class StrategyInstanceAdmin(ModelActionsAdminMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('strategy_model', 'display_instruments', 'is_active', 'description', 'last_tasks')
    list_filter = ('is_active', 'strategy_model')
    search_fields = ('instruments__symbol', 'instruments__venue', 'strategy_model__name', 'description')
    autocomplete_fields = ('strategy_model',)
    list_sections = [MessageHistorySection]
    inlines = [StrategyInstrumentInline, BacktestInline]
    actions = ['clone_action']
    actions_row = ['clone_row_action']

    @admin.display(description=_("Instruments"))
    def display_instruments(self, obj):
        instruments = list(obj.strategy_instruments.select_related('instrument'))
        if not instruments:
            return "-"
        symbols = [si.instrument.symbol for si in instruments if si.instrument]
        if not symbols:
            return "-"
        first_three = ", ".join(symbols[:3])
        count = len(symbols)
        url = reverse("admin:argo_instrument_changelist") + f"?strategy_instance={obj.id}"
        link_label = _("View all %(count)d") % {"count": count} if count > 3 else _("View")
        return format_html(
            '{} <a href="{}" class="font-semibold text-primary-600 hover:underline">({})</a>',
            first_three,
            url,
            link_label,
        )

    @admin.action(description=_("Clone selected strategy instance(s)"))
    def clone_action(self, request, queryset):
        count = 0
        for item in queryset:
            item.clone()
            count += 1
        self.message_user(
            request,
            _("Successfully cloned %(count)d strategy instance(s).") % {"count": count}
        )

    @action(description=_("Clone"), icon="content_copy")
    def clone_row_action(self, request, object_id: int):
        obj = self.get_object(request, object_id)
        if obj:
            clone = obj.clone()
            self.message_user(request, _("Successfully cloned %(obj)s.") % {"obj": str(clone)})
            return redirect(reverse("admin:argo_strategyinstance_change", args=[clone.pk]))
        return redirect(reverse("admin:argo_strategyinstance_changelist"))


class HistoricalDataInstrumentFilter(admin.SimpleListFilter):
    title = _("Instrument")
    parameter_name = "instrument"

    def lookups(self, request, model_admin):
        from .models import Instrument
        instruments = (
            Instrument.objects.filter(historical_datasets__isnull=False)
            .distinct()
            .order_by("symbol", "venue")
        )
        return [
            (str(i.id), f"{i.symbol}.{i.venue}" if i.venue else i.symbol)
            for i in instruments
        ]

    def queryset(self, request, queryset):
        val = self.value() or request.GET.get("instrument__id__exact")
        if val:
            return queryset.filter(instrument_id=val)
        return queryset


@admin.register(HistoricalData)
class HistoricalDataAdmin(AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('instrument', 'bar_type', 'start_date', 'end_date', 'bar_count', 'display_parquet_file', 'display_health_check', 'created_at', 'last_tasks')
    list_filter = (HistoricalDataInstrumentFilter, 'bar_type',)
    search_fields = ('instrument__symbol', 'bar_type', 'catalog_path')
    autocomplete_fields = ('instrument',)
    readonly_fields = ('created_at', 'updated_at', 'catalog_path', 'display_parquet_file', 'display_health_check', 'display_summary', 'last_tasks')
    actions = ['sync_data_action', 'health_check_action', 'restart_ib_gateway_action']

    @admin.display(description=_("Parquet File"))
    def display_parquet_file(self, obj):
        file = obj.parquet_file
        if file and file.exists():
            size_kb = file.stat().st_size / 1024
            size_str = f"{size_kb / 1024:.2f} MB" if size_kb >= 1024 else f"{size_kb:.1f} KB"
            return format_html(
                '<span class="font-mono text-xs font-semibold text-green-700" title="{}">&#10003; {} ({})</span>',
                str(file),
                file.name,
                size_str,
            )
        err = (obj.summary or {}).get("error")
        if err:
            short_err = err[:32] + "..." if len(err) > 32 else err
            return format_html(
                '<span class="text-xs font-medium text-red-600" title="{}">&#10007; Missing ({})</span>',
                err,
                short_err,
            )
        return mark_safe('<span class="text-xs font-medium text-amber-600">&#10007; Missing</span>')

    @admin.display(description=_("Health Check"))
    def display_health_check(self, obj):
        res = obj.health_check()
        from .models import ParquetHealthResult
        if res.status == ParquetHealthResult.STATUS_HEALTHY:
            return format_html(
                '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400" title="{}">&#10003; Healthy</span>',
                res.message,
            )
        elif res.status == ParquetHealthResult.STATUS_WARNING:
            return format_html(
                '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400" title="{}">&#9888; Warning</span>',
                res.message,
            )
        elif res.status == ParquetHealthResult.STATUS_MISSING:
            return format_html(
                '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300" title="{}">&#10007; Missing</span>',
                res.message,
            )
        else:
            return format_html(
                '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400" title="{}">&#10007; Corrupt</span>',
                res.message,
            )

    @admin.display(description=_("Summary / Diagnostics"))
    def display_summary(self, obj):
        if not obj.summary:
            return "-"
        import json
        return format_html("<pre class='text-xs' style='max-width: 600px; overflow-x: auto;'>{}</pre>", json.dumps(obj.summary, indent=2))

    @admin.action(description=_("Sync historical data (complete/extend Parquet catalog)"))
    def sync_data_action(self, request, queryset):
        count = 0
        for item in queryset:
            item.task_from_action(item.ACTION_SYNC_DATA, request.user)
            count += 1
        self.message_user(request, _(f"Triggered catalog sync task for {count} dataset(s)."))

    @admin.action(description=_("Run Parquet health check"))
    def health_check_action(self, request, queryset):
        healthy_count = 0
        issues = []
        for item in queryset:
            res = item.health_check()
            if res.is_healthy:
                healthy_count += 1
            else:
                issues.append(f"{item.instrument.symbol}: {res.message}")
        msg = _("Health Check: %(healthy)d healthy dataset(s).") % {"healthy": healthy_count}
        if issues:
            msg += " " + _("Issues: %(issues)s") % {"issues": "; ".join(issues[:5])}
        self.message_user(request, msg)

    @admin.action(description=_("Verify & Restart IB Gateway"))
    def restart_ib_gateway_action(self, request, queryset):
        from project_guillermo.settings import TASK_TYPE_IB_GATEWAY_RESTART
        from task.models import Task
        task = Task.objects.create(
            task_type=TASK_TYPE_IB_GATEWAY_RESTART,
            created_by=request.user,
            payload={"force": True}
        )
        task.process()
        self.message_user(request, _("Triggered IB Gateway verification & restart task #%(task_id)s.") % {"task_id": task.id})


class BacktestRunInline(BacktestFloatDisplayMixin, TabularInline):
    model = BacktestRun
    extra = 0
    fields = ('id', 'created_at', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'total_trades', 'view_report')
    readonly_fields = ('id', 'created_at', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'total_trades', 'view_report')
    show_change_link = True

    def view_report(self, obj):
        if obj.id and obj.html_report:
            url = reverse('admin:argo_backtestrun_report', args=[obj.id])
            return format_html('<a href="{}" target="_blank" class="font-semibold text-primary-600 hover:underline">{}</a>', url, _("View HTML"))
        return "-"
    view_report.short_description = _("Tearsheet")


@admin.register(Backtest)
class BacktestAdmin( ModelActionsAdminMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin, BacktestFloatDisplayMixin):
    list_display = ('__str__', 'strategy_instance', 'is_data_covered', 'total_pnl', 'return_pct', 'sharpe_ratio', 'last_tasks')
    list_filter = ('optimization_objective', 'strategy_instance__strategy_model')
    search_fields = ('name', 'strategy_instance__instruments__symbol', 'strategy_instance__strategy_model__name')
    autocomplete_fields = ('strategy_instance',)
    readonly_fields = (
        'total_pnl',
        'return_pct',
        'sharpe_ratio',
        'sortino_ratio',
        'calmar_ratio',
        'max_drawdown_pct',
        'profit_factor',
        'win_rate',
        'total_trades',
        'best_params',
        'leaderboard',
    )
    fieldsets = (
        (_("Configuration"), {
            "fields": ("strategy_instance", "name", ("start_date", "end_date"), ("initial_capital", "commission_rate")),
        }),
        (_("Optimization Settings"), {
            "fields": ("optimization_objective", "params_override", "param_grid"),
            "classes": ("collapse",),
        }),
        (_("Performance Metrics"), {
            "fields": (
                ("total_pnl", "return_pct"),
                ("sharpe_ratio", "sortino_ratio", "calmar_ratio"),
                ("max_drawdown_pct", "profit_factor", "win_rate"),
                "total_trades",
            ),
        }),
        (_("Optimization Results"), {
            "fields": ("best_params", "leaderboard"),
            "classes": ("collapse",),
        }),
    )
    formfield_overrides = {
        models.FloatField: {"widget": forms.NumberInput(attrs={"step": "0.0001"})},
    }
    list_sections = [MessageHistorySection, BacktestRunSection]
    changeform_sections = [BacktestRunSection]
    inlines = [BacktestRunInline]
    actions = ['apply_best_params_action']

    class Media:
        js = ('js/admin_argo.js',)

    @admin.display(boolean=True, description=_("Data Covered"))
    def is_data_covered(self, obj):
        return obj.is_covered()

    @admin.action(description=_("Apply winning parameters to StrategyInstance"))
    def apply_best_params_action(self, request, queryset):
        count = 0
        for bt in queryset:
            if bt.best_params:
                bt.apply_best_params_to_instance()
                count += 1
        self.message_user(request, _(f"Applied optimal parameters from {count} backtest(s) to StrategyInstance(s)."))


@admin.register(BacktestRun)
class BacktestRunAdmin(BacktestFloatDisplayMixin, AjaxSectionAdminMixin, ModelAdmin):
    list_display = ('id', 'strategy_instance', 'backtest', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'total_trades', 'created_at', 'view_report_link')
    list_filter = ('created_at', 'strategy_instance__strategy_model')
    search_fields = ('id', 'strategy_instance__strategy_model__name', 'strategy_instance__instruments__symbol')
    readonly_fields = (
        'created_at',
        'display_html_report',
        'display_code',
        'display_log',
        'display_config',
        'total_pnl',
        'return_pct',
        'sharpe_ratio',
        'sortino_ratio',
        'calmar_ratio',
        'max_drawdown_pct',
        'profit_factor',
        'win_rate',
        'total_trades',
    )
    fieldsets = (
        (_("Run Information"), {
            "fields": ("strategy_instance", "backtest", "created_at", "total_pnl", "return_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio", "max_drawdown_pct", "profit_factor", "win_rate", "total_trades"),
        }),
        (_("Interactive Report"), {
            "fields": ("display_html_report",),
        }),
        (_("Execution Log"), {
            "fields": ("display_log",),
        }),
        (_("Executed Strategy Code"), {
            "fields": ("display_code",),
        }),
        (_("Final Configuration"), {
            "fields": ("display_config",),
        }),
    )
    autocomplete_fields = ('backtest', 'strategy_instance')

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:run_id>/report/', self.admin_site.admin_view(self.report_view), name='argo_backtestrun_report'),
        ]
        return custom_urls + urls

    def report_view(self, request, run_id):
        from django.shortcuts import get_object_or_404
        from django.http import HttpResponse
        run = get_object_or_404(BacktestRun, id=run_id)
        return HttpResponse(run.html_report or "<h1>No Tearsheet Report Generated</h1>", content_type="text/html")

    def view_report_link(self, obj):
        if obj.html_report:
            url = reverse('admin:argo_backtestrun_report', args=[obj.id])
            return format_html('<a href="{}" target="_blank" class="font-semibold text-primary-600 hover:underline">{}</a>', url, _("View HTML Tearsheet"))
        return "-"
    view_report_link.short_description = _("Tearsheet")

    def display_html_report(self, obj):
        if not obj.html_report:
            return _("No HTML report generated.")
        url = reverse('admin:argo_backtestrun_report', args=[obj.id])
        return format_html(
            '<div class="mb-2"><a href="{}" target="_blank" class="font-bold text-primary-600 hover:underline">🔗 Open Tearsheet in New Tab</a></div>'
            '<iframe src="{}" style="width: 100%; height: 800px; border: 1px solid #ccc; border-radius: 8px;"></iframe>',
            url, url
        )
    display_html_report.short_description = _("Interactive HTML Tearsheet")

    def display_code(self, obj):
        if not obj.code:
            return "-"
        return format_html('<pre style="max-height: 400px; overflow-y: auto; background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;"><code>{}</code></pre>', obj.code)
    display_code.short_description = _("Executed Strategy Code")

    def display_log(self, obj):
        if not obj.log:
            return "-"
        return format_html('<pre style="max-height: 400px; overflow-y: auto; background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;"><code>{}</code></pre>', obj.log)
    display_log.short_description = _("Execution Log")

    def display_config(self, obj):
        if not obj.config:
            return "-"
        import json
        formatted = json.dumps(obj.config, indent=2)
        return format_html('<pre style="max-height: 300px; overflow-y: auto; background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 6px;"><code>{}</code></pre>', formatted)
    display_config.short_description = _("Final Execution Configuration")




@admin.register(Scanner)
class ScannerAdmin(ModelAdmin):
    list_display = ('name', 'scanner_class_path', 'description')
    search_fields = ('name', 'scanner_class_path')


@admin.register(Signal)
class SignalAdmin(ModelAdmin):
    list_display = ('scanner', 'instrument_id', 'signal_type', 'status', 'confidence', 'generated_at')
    list_filter = ('signal_type', 'status', 'scanner')
    search_fields = ('instrument_id', 'scanner__name')
    autocomplete_fields = ('scanner',)
    readonly_fields = ('generated_at',)


@admin.register(Recommendation)
class RecommendationAdmin(ModelAdmin):
    list_display = ('signal', 'recommended_strategy', 'status', 'created_at')
    list_filter = ('status', 'recommended_strategy')
    search_fields = ('signal__instrument_id', 'recommended_strategy__name', 'justification')
    autocomplete_fields = ('signal', 'recommended_strategy')
    readonly_fields = ('created_at',)


@admin.register(InstrumentGroup)
class InstrumentGroupAdmin(ModelActionsAdminMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('name', 'code', 'instrument_count', 'is_active', 'last_tasks')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'prompt')
    list_sections = [MessageHistorySection]
    list_refresh = ['instrument_count']

    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(
            instrument_count_annotated=Count("linked_instruments", distinct=True)
        )

    def instrument_count(self, obj):
        count = getattr(obj, "instrument_count_annotated", None)
        if count is None:
            count = obj.linked_instruments.count() if hasattr(obj, "linked_instruments") else 0
        url = reverse("admin:argo_instrument_changelist") + f"?group={obj.id}"
        label = _("Instruments") if count != 1 else _("Instrument")
        if count == 0:
            return format_html(
                '<a href="{}" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">0 {}</a>',
                url,
                label
            )
        return format_html(
            '<a href="{}" class="font-semibold text-primary-600 hover:underline">{} {}</a>',
            url,
            count,
            label
        )
    instrument_count.short_description = _("Instruments")
    instrument_count.admin_order_field = "instrument_count_annotated"

class InstrumentGroupFilter(admin.SimpleListFilter):
    title = _("Group")
    parameter_name = "group"

    def lookups(self, request, model_admin):
        return [(g.id, f"{g.name} ({g.code})") for g in InstrumentGroup.objects.all().order_by("name")]

    def queryset(self, request, queryset):
        val = self.value() or request.GET.get("groups__id__exact")
        if val:
            return queryset.filter(groups__id=val).distinct()
        return queryset


class StrategyInstanceFilter(admin.SimpleListFilter):
    title = _("Strategy Instance")
    parameter_name = "strategy_instance"

    def lookups(self, request, model_admin):
        from .models import StrategyInstance
        return [
            (str(si.id), str(si))
            for si in StrategyInstance.objects.select_related('strategy_model').all().order_by("id")
        ]

    def queryset(self, request, queryset):
        val = self.value() or request.GET.get("strategy_instance") or request.GET.get("strategy_instances__id__exact")
        if val:
            return queryset.filter(strategy_instances__id=val).distinct()
        return queryset


@admin.register(Instrument)
class InstrumentAdmin(ModelActionsAdminMixin, ModelAdmin):
    list_display = ('symbol', 'exchange', 'primary_exchange', 'currency', 'display_historical_data', 'display_groups')
    list_filter = (InstrumentGroupFilter, StrategyInstanceFilter, 'exchange', 'currency')
    search_fields = (
        'symbol',
        'groups__code',
        'groups__name',
    )
    filter_horizontal = ('groups',)
    readonly_fields = ('display_historical_data',)
 
    def get_queryset(self, request):
        from django.db.models import Count
        return super().get_queryset(request).annotate(
            historical_data_count_annotated=Count("historical_datasets", distinct=True)
        )

    def display_groups(self, obj):
        groups = obj.groups.all()
        if not groups:
            return "-"
        links = [
            format_html(
                '<a href="{}" class="font-medium text-primary-600 hover:underline">{} <span class="text-xs text-gray-500 font-mono">({})</span></a>',
                reverse("admin:argo_instrument_changelist") + f"?group={g.id}",
                g.name,
                g.code
            )
            for g in groups
        ]
        return mark_safe(", ".join(links))
    display_groups.short_description = _("Groups")

    @admin.display(description=_("Historical Data"), ordering="historical_data_count_annotated")
    def display_historical_data(self, obj):
        count = getattr(obj, "historical_data_count_annotated", None)
        if count is None:
            count = obj.historical_datasets.count() if hasattr(obj, "historical_datasets") else 0
        url = reverse("admin:argo_historicaldata_changelist") + f"?instrument={obj.id}"
        label = _("Datasets") if count != 1 else _("Dataset")
        if count == 0:
            return format_html(
                '<a href="{}" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">0 {}</a>',
                url,
                label
            )
        return format_html(
            '<a href="{}" class="font-semibold text-primary-600 hover:underline">{} {}</a>',
            url,
            count,
            label
        )


