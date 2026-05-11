"""Runtime compatibility patches for deployed platform/runtime combinations."""
from copy import copy


def patch_django_template_context_copy() -> None:
    """
    Fix Django 5.1 template context copying on Python 3.14.

    Django 5.1's BaseContext.__copy__ uses copy(super()), which raises
    AttributeError on Python 3.14 when admin inclusion tags copy the template
    context. The patch mirrors Django's intended behavior by cloning the
    context object and copying its dict stack.
    """
    try:
        from django.template.context import BaseContext, Context
    except Exception:
        return

    if getattr(BaseContext, '_biogas_py314_copy_patch', False):
        return

    def base_context_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        if hasattr(self, '__dict__'):
            duplicate.__dict__.update(self.__dict__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    def context_copy(self):
        duplicate = base_context_copy(self)
        duplicate.render_context = copy(self.render_context)
        return duplicate

    BaseContext.__copy__ = base_context_copy
    Context.__copy__ = context_copy
    BaseContext._biogas_py314_copy_patch = True
