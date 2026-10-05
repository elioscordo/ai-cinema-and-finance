from django.db import transaction


class CloneModelMixin:
    """
    Template Method mixin providing atomic model duplication.
    Handles primary key/ID resets, field overrides, and hooks for related child models.
    """

    def _prepare_clone_fields(self, clone_obj, **kwargs):
        """Hook to adjust or reset fields on the clone instance prior to saving."""
        if hasattr(clone_obj, 'action') and 'action' not in kwargs:
            clone_obj.action = None
        if hasattr(clone_obj, 'description') and clone_obj.description and 'description' not in kwargs:
            clone_obj.description = f"{clone_obj.description} (Copy)"
        if hasattr(clone_obj, 'name') and clone_obj.name and 'name' not in kwargs:
            clone_obj.name = f"{clone_obj.name} (Copy)"

    def _clone_m2m_relationships(self, new_instance) -> None:
        """Automatically copies standard auto-created through table ManyToMany relationships."""
        for m2m in self._meta.many_to_many:
            if getattr(m2m.remote_field.through._meta, 'auto_created', False):
                source_qs = getattr(self, m2m.name).all()
                getattr(new_instance, m2m.name).set(source_qs)

    def _clone_related(self, new_instance, **kwargs):
        """Hook to clone related models or through-table rows. Subclasses should override this."""
        self._clone_m2m_relationships(new_instance)

    @transaction.atomic
    def clone(self, **kwargs):
        """
        Clones the current model instance and saves it to the database.
        Applies kwargs as field overrides, runs field preparation hooks,
        persists the new object, and executes relation cloning hooks.
        """
        if self.pk:
            clone_obj = self.__class__.objects.get(pk=self.pk)
        else:
            clone_obj = self

        clone_obj.pk = None
        clone_obj.id = None
        clone_obj._state.adding = True

        self._prepare_clone_fields(clone_obj, **kwargs)

        for key, value in kwargs.items():
            setattr(clone_obj, key, value)

        clone_obj.save()
        self._clone_related(clone_obj, **kwargs)
        return clone_obj
