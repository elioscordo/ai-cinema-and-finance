from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
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
    IBContract,
)
from .sections import StrategyCodeSection
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
    list_filter = ('key', 'instrument__asset_class', 'instrument__venue')
    search_fields = ('key', 'instrument__symbol', 'instrument__venue', 'strategy_instance__strategy_model__name')
    autocomplete_fields = ('strategy_instance', 'instrument')


class BacktestInline(TabularInline):
    model = Backtest
    extra = 0
    fields = ('name', 'start_date', 'end_date', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'total_trades', 'last_tasks')
    readonly_fields = ('total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'total_trades', 'last_tasks')
    show_change_link = True


@admin.register(StrategyInstance)
class StrategyInstanceAdmin(ModelActionsAdminMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('strategy_model', 'instrument', 'is_active', 'description', 'last_tasks')
    list_filter = ('is_active', 'strategy_model')
    search_fields = ('instruments__symbol', 'instruments__venue', 'strategy_model__name', 'description')
    autocomplete_fields = ('strategy_model',)
    list_sections = [MessageHistorySection]
    inlines = [StrategyInstrumentInline, BacktestInline]


@admin.register(HistoricalData)
class HistoricalDataAdmin(AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('instrument', 'bar_type', 'start_date', 'end_date', 'bar_count', 'source', 'created_at', 'last_tasks')
    list_filter = ('bar_type', 'instrument__asset_class')
    search_fields = ('instrument__symbol', 'bar_type', 'catalog_path')
    autocomplete_fields = ('instrument',)
    readonly_fields = ('created_at', 'updated_at', 'catalog_path', 'source', 'last_tasks')
    actions = ['load_data_action']

    @admin.action(description=_("Load historical data (create Parquet catalog)"))
    def load_data_action(self, request, queryset):
        count = 0
        for item in queryset:
            item.load_data(as_task=True, owner=request.user)
            count += 1
        self.message_user(request, _(f"Triggered catalog load task for {count} dataset(s)."))


class BacktestRunInline(TabularInline):
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
class BacktestAdmin(ModelActionsAdminMixin, SimpleHistoryAdmin, AjaxSectionAdminMixin, AjaxTaskModelAdmin, ModelAdmin):
    list_display = ('__str__', 'strategy_instance', 'is_data_covered', 'total_pnl', 'return_pct', 'sharpe_ratio', 'max_drawdown_pct', 'win_rate', 'total_trades', 'last_tasks')
    list_filter = ('optimization_objective', 'strategy_instance__strategy_model')
    search_fields = ('name', 'strategy_instance__instruments__symbol', 'strategy_instance__strategy_model__name')
    autocomplete_fields = ('strategy_instance',)
    list_sections = [MessageHistorySection]
    inlines = [BacktestRunInline]
    actions = ['apply_best_params_action']

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
class BacktestRunAdmin(AjaxSectionAdminMixin, ModelAdmin):
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

class IBContractInline(StackedInline):
    model = IBContract
    extra = 0
    can_delete = False


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


@admin.register(Instrument)
class InstrumentAdmin(ModelAdmin):
    list_display = ('symbol', 'venue', 'asset_class', 'currency', 'display_groups', 'price_precision', 'lot_size', 'is_active')
    list_filter = (InstrumentGroupFilter, 'asset_class', 'venue', 'currency', 'is_active')
    search_fields = (
        'symbol',
        'venue',
        'currency',
        'groups__code',
        'groups__name',
        'ib_contract__con_id',
        'ib_contract__local_symbol',
    )
    filter_horizontal = ('groups',)
    inlines = [IBContractInline]

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
        from django.utils.safestring import mark_safe
        return mark_safe(", ".join(links))
    display_groups.short_description = _("Groups")


@admin.register(IBContract)
class IBContractAdmin(ModelAdmin):
    list_display = ('instrument', 'sec_type', 'exchange', 'con_id', 'expiration', 'strike', 'option_right')
    list_filter = ('sec_type', 'exchange', 'option_right')
    search_fields = ('instrument__symbol', 'con_id', 'local_symbol')
    autocomplete_fields = ('instrument',)


