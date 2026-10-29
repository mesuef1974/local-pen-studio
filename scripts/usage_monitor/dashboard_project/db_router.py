"""Keep Django authentication separate from the application-data database."""


class UsageReadOnlyRouter:
    workflow_alias = "workflow"
    workflow_app_label = "workflow_admin"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.workflow_app_label:
            return self.workflow_alias
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.workflow_app_label:
            return self.workflow_alias
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self.workflow_app_label in {obj1._meta.app_label, obj2._meta.app_label}:
            return obj1._state.db == obj2._state.db
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.workflow_app_label or db == self.workflow_alias:
            return False
        return None
