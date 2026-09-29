from django.contrib import admin

class AdminActionsMixin:
    @admin.action(description="Clone selected items")
    def clone(self, request, queryset):
        for obj in queryset:
            if hasattr(obj, 'name') and obj.name:
                obj.name = f"{obj.name} (Clone)"
            obj.save()
            
        self.message_user(request, "Selected items have been cloned.")


class ModelActionsAdminMixin:
    """
    Admin mixin that dynamically creates changelist admin actions for all
    actions configured in the model (via ACTION_CHOICES and optional ACTIONS_NO_INPUT).
    """

    def _execute_model_action(self, request, obj, action_code):
        """Triggers the task for an object via task_from_action or generic task creation."""
        if hasattr(obj, "task_from_action"):
            obj.task_from_action(action_code, request.user)
        else:
            from task.models import Task
            Task.createTaskIfQueueEnabled(
                subject=obj,
                task_type=action_code,
                owner=request.user,
            )

    def _build_admin_action(self, action_code, description, action_name):
        """Constructs an action callback with proper signature and localized message."""
        def action_func(modeladmin, request, queryset):
            for obj in queryset:
                modeladmin._execute_model_action(request, obj, action_code)
            model_label = modeladmin.model._meta.verbose_name_plural
            modeladmin.message_user(
                request,
                f"Action '{description}' triggered for {queryset.count()} selected {model_label}."
            )

        action_func.__name__ = action_name
        action_func.short_description = description
        return action_func

    def get_actions(self, request):
        """Dynamically populates admin actions from the model's configured action choices."""
        actions = super().get_actions(request)
        model = getattr(self, "model", None)
        if not model:
            return actions

        from django.utils.text import slugify
        from django.utils.translation import gettext_lazy as _

        action_choices = dict(getattr(model, "ACTION_CHOICES", ()))
        no_input_actions = getattr(model, "ACTIONS_NO_INPUT",  None)
        target_codes = no_input_actions if no_input_actions is not None else list(action_choices.keys())

        for action_code in target_codes:
            description = action_choices.get(action_code, action_code)
            action_name = f"action_{slugify(str(action_code)).replace('-', '_')}"
            func = self._build_admin_action(action_code, description, action_name)
            actions[action_name] = (func, action_name, description)

        return actions