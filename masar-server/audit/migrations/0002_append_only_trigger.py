"""Enforce append-only audit rows inside PostgreSQL, below the ORM.

The only raw SQL in the server: the ORM cannot express a trigger.
"""
from django.db import migrations

CREATE = """
CREATE FUNCTION masar_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit events are append-only';
END $$;
CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION masar_audit_append_only();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_auditevent
    FOR EACH STATEMENT EXECUTE FUNCTION masar_audit_append_only();
"""
DROP = """
DROP TRIGGER audit_append_only ON audit_auditevent;
DROP TRIGGER audit_no_truncate ON audit_auditevent;
DROP FUNCTION masar_audit_append_only();
"""


def run(sql):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(sql, params=None)
    return apply


class Migration(migrations.Migration):
    dependencies = [('audit', '0001_initial')]
    operations = [migrations.RunPython(run(CREATE), run(DROP))]
