import inspect
from collections import OrderedDict, namedtuple

from django.core import validators
from django.core.exceptions import ImproperlyConfigured
from django.utils import six
from django.utils.text import capfirst

from rest_framework.utils.field_mapping import needs_label

from mongoengine.base.common import get_document
import mongoengine
from mongoengine import fields as me_fields

from rest_framework_mongoengine.validators import UniqueValidator

FieldInfo = namedtuple('FieldResult', [
    'pk',  # Model field instance
    'fields',  # Dict of field name -> model field instance
    'forward_relations',  # Dict of field name -> RelationInfo
    'reverse_relations',  # Dict of field name -> RelationInfo
    'fields_and_pk',  # Shortcut for 'pk' + 'fields'
    'relations'  # Shortcut for 'forward_relations' + 'reverse_relations'
])

RelationInfo = namedtuple('RelationInfo', [
    'model_field',
    'related',
    'to_many',
    'has_through_model'
])


def _resolve_model(obj):
    """
    Inherited from rest_framework.utils.model_meta
    Overridden for MongoDB compability
    """
    if isinstance(obj, six.string_types) and len(obj.split('.')) == 2:
        app_name, model_name = obj.split('.')
        resolved_model = get_document(model_name)
        if resolved_model is None:
            msg = "Mongoengine did not return a model for {0}.{1}"
            raise ImproperlyConfigured(msg.format(app_name, model_name))
        return resolved_model
    elif inspect.isclass(obj) and issubclass(obj, mongoengine.BaseDocument):
        return obj
    raise ValueError("{0} is not a MongoDB Document".format(obj))

def get_field_info(model):
    """
    Given a model class, returns a `FieldInfo` instance, which is a
    `namedtuple`, containing metadata about the various field types on the model
    including information about their relationships.
    """
    # Deal with the primary key.
    if issubclass(model, mongoengine.EmbeddedDocument):
        pk = None
    else:
        pk = model._fields[model._meta['id_field']]

    # Deal with regular fields.
    fields = OrderedDict()

    for field_name in model._fields_ordered:
        fields[field_name] = model._fields[field_name]

    # Deal with forward relationships.
    # Pass forward relations since there is no relations on mongodb
    forward_relations = OrderedDict()

    # Deal with reverse relationships.
    # Pass reverse relations since there is no relations on mongodb
    reverse_relations = OrderedDict()

    # Shortcut that merges both regular fields and the pk,
    # for simplifying regular field lookup.
    fields_and_pk = OrderedDict()
    fields_and_pk['pk'] = pk
    fields_and_pk[getattr(pk, 'name', 'pk')] = pk
    fields_and_pk.update(fields)

    # Shortcut that merges both forward and reverse relationships

    relations = OrderedDict(
        list(forward_relations.items()) +
        list(reverse_relations.items())
    )

    return FieldInfo(pk, fields, forward_relations, reverse_relations, fields_and_pk, relations)


def is_abstract_model(model):
    return hasattr(model, 'meta') and model.meta.get('abstract',False)

NUMERIC_FIELD_TYPES = (
    me_fields.IntField,
    me_fields.LongField,
    me_fields.FloatField,
    me_fields.DecimalField
)

def get_field_kwargs(field_name, model_field):
    """
    Creates a default instance of a basic non-relational field.
    """
    kwargs = {}
    validator_kwarg = []
    if model_field.validation:
        validator_kwarg.append(model_field.validation)

    # The following will only be used by ModelField classes.
    # Gets removed for everything else.
    kwargs['model_field'] = model_field

    if model_field.verbose_name and needs_label(model_field, field_name):
        kwargs['label'] = capfirst(model_field.verbose_name)

    if model_field.help_text:
        kwargs['help_text'] = model_field.help_text

    if isinstance(model_field, me_fields.DecimalField):
        precision = model_field.precision
        max_value = getattr(model_field,'max_value',None)
        if max_value is not None:
            max_length = len(str(max_value)) + precision
        else:
            max_length = 65536
        kwargs['decimal_places'] = precision
        kwargs['max_digits'] = max_length

    if isinstance(model_field, me_fields.SequenceField) or model_field.primary_key or model_field.db_field == '_id':
        # If this field is read-only, then return early.
        # Further keyword arguments are not valid.
        kwargs['read_only'] = True
        return kwargs

    kwargs['required'] = model_field.required

    if model_field.default:
        kwargs['required'] = False

    if model_field.default and not isinstance(model_field, me_fields.ComplexBaseField):
        kwargs['default'] = model_field.default

    if model_field.null:
        kwargs['allow_null'] = True

    if model_field.choices:
        # If this model field contains choices, then return early.
        # Further keyword arguments are not valid.
        kwargs['choices'] = model_field.choices
        return kwargs

    max_length = getattr(model_field, 'max_length', None)
    if max_length is not None and isinstance(model_field, me_fields.StringField):
        kwargs['max_length'] = max_length

    min_length = getattr(model_field, 'min_length', None)
    if min_length is not None and isinstance(model_field, me_fields.StringField):
        kwargs['min_length'] = min_length

    max_value = getattr(model_field, 'max_value', None)
    if max_value is not None and isinstance(model_field, NUMERIC_FIELD_TYPES):
        kwargs['max_value'] = max_value

    min_value = getattr(model_field, 'min_value', None)
    if min_value is not None and isinstance(model_field, NUMERIC_FIELD_TYPES):
        kwargs['min_value'] = min_value

    if getattr(model_field, 'unique', False):
        validator = UniqueValidator(
            queryset=model_field.model._default_manager,
            message=None)
        validator_kwarg.append(validator)

    if validator_kwarg:
        kwargs['validators'] = validator_kwarg

    return kwargs