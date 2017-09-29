"""
Version 2x: https://swagger.io/docs/specification/2-0/basic-structure/
Version 3x: https://swagger.io/specification
"""

import json
import typing
from base64 import b64encode
from collections import OrderedDict, Mapping, Sequence, Iterable, Callable, Reversible, Set
from copy import deepcopy, copy
from http.client import HTTPResponse
from io import IOBase, UnsupportedOperation
from itertools import chain
from numbers import Number
from typing import List, Union, Any, AnyStr
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

import yaml
from jsonpointer import JsonPointer, resolve_pointer, set_pointer

from oapi import properties
from oapi.errors import ValidationError

NoneType = type(None)


class Null(object):
    """
    This is a stand-in for explicit inclusion of a null value.
    """
    pass


NULL = Null()


def dump(data):
    # type: (Any) -> Union[Object, str, Number, bytes, typing.Collection]
    if hasattr(data, '_dump'):
        return data._dump()
    elif isinstance(data, Null):
        return None
    elif isinstance(data, (bytes, bytearray)):
        return b64encode(data)
    # elif isinstance(data, (str, Number, bool)):
    #     return data
    # elif isinstance(data, dict):
    #     if isinstance(data, Reversible):
    #         return OrderedDict([
    #             (k, dump(v)) for k, v in data.items()
    #         ])
    #     else:
    #         return OrderedDict([
    #             (k, dump(data[k])) for k in
    #             sorted(
    #                 k for k, v in data.items() if v is not None
    #             )
    #         ])
    # elif isinstance(data, (Set, Sequence)) and not isinstance(data, (str, bytes)):
    #     return tuple(dump(i) for i in data)
    elif hasattr(data, '__bytes__'):
        return b64encode(bytes(data))
    else:
        return data


def dumps(data, data_format='json'):
    # type: (Any, str) -> str
    if data_format not in ('json', 'yaml'):
        data_format = data_format.lower()
        if data_format not in ('json', 'yaml'):
            raise ValueError(
                'Supported `oapi.model.dumps()` `data_format` values include "json" and "yaml" (not "%s").' % data_format
            )
    if data_format == 'json':
        return json.dumps(dump(data))
    elif data_format == 'yaml':
        return yaml.dump(dump(data))


def get_property_definitions(o):
    # type: (Object) -> typing.Sequence[properties.Property]
    return o._properties


def set_property_definitions(class_object, class_properties):
    # type: (type, Union[typing.Sequence[Tuple[str, Property]], typing.Mapping[str, Property]]) -> None
    if not isinstance(properties, dict):
        class_properties = OrderedDict(class_properties)
    class_object._properties = class_properties


def get_property_definition(class_or_instance, property_name):
    # type: (type, str, Property) -> None
    if not isinstance(class_or_instance._properties, dict):
        class_or_instance._properties = OrderedDict()
    return class_or_instance._properties[property_name]


def set_property_definition(class_or_instance, property_name, property):
    # type: (type, str, Property) -> None
    if not isinstance(class_or_instance._properties, dict):
        class_or_instance._properties = OrderedDict()
    class_or_instance._properties[property_name] = property


def set_version(data, specification, version):
    # type: (Any, str, typing.Hashable) -> Any
    if isinstance(data, Object):
        old_properties = get_property_definitions(data)
        new_properties = deepcopy(old_properties)
        for n, p in old_properties.items():
            if p.versions is not None:
                version_match = False
                specification_match = False
                for v in p.versions:
                    if v.specification == specification:
                        specification_match = True
                        if v == version:
                            version_match = True
                            if v.types is not None:
                                new_properties[n].types = v.types
                            break
                if specification_match and (not version_match):
                    del new_properties[n]
        set_property_definitions(data, new_properties)
        for n, p in new_properties.items():
            set_version(getattr(data, n), specification, version)
    elif isinstance(data, (Set, Sequence)) and not isinstance(data, (str, bytes)):
        for d in data:
            set_version(d, specification, version)
    elif isinstance(data, dict):
        for k, v in data.items():
            set_version(v, specification, version)


def _resolve_ref(
    ref,  # type: str
    root,  # type: Union[Object, Sequence]
    url=None,  # type: Optional[str]
    open_function=urlopen,  # type: Union[typing.Callable, Sequence[typing.Callable]]
    references=None
):
    if references is None:
        references = {}
    if ref[0] == '#':
        document = root
        pointer = ref[1:]
    else:
        parts = ref.split('#')
        ref_url = parts[0]
        if url:
            parse_result = urlparse(ref_url)
            if parse_result.scheme:
                url = ref_url
            else:
                url = '%s/%s' % (
                    '/'.join(url.rstrip('/').split('/')[:-1]),
                    ref_url.lstrip('/ ')
                )
        else:
            url = ref_url
        if len(parts) < 2:
            pointer = None
        else:
            pointer = '#'.join(parts[1:])
        try:
            document = loads(open_function(url))
        except HTTPError as e:
            e.msg = e.msg + ': ' + url
            raise e
    if pointer is None:
        data = document
    else:
        url_pointer = '%s#%s' % (url or '', pointer)
        if url_pointer in references:
            data = references[url_pointer]
        else:
            data = resolve_pointer(document, pointer)
            references = copy(references)
            references[url_pointer] = url_pointer
    return data, document, url, references


def resolve_references(
    data,  # type: Union[Object, typing.Mapping, typing.Sequence]
    url=None,  # type: Optional[str]
    open_function=urlopen,  # type: Union[typing.Callable, Sequence[typing.Callable]]
    root=None,  # type: Union[Object, Sequence]
    references=None,  # type: Optional[Sequence[str]]
):
    # type: (...) -> Union[Object, Mapping, Sequence]
    if references is None:
        references = {}
    try:
        data = deepcopy(data)
    except TypeError as e:
        e.args = tuple(
            chain(
                (
                    '%s%s' % (
                        e.args[0] + '\n' if e.args else '',
                        dumps(data),
                    ),
                ),
                e.args[1:] if e.args else []
            )
        )
        raise e
    if root is None:
        root = data
    if isinstance(data, Object):
        if (url is None) and data._url:
            url = data._url
        for pn, p in get_property_definitions(data).items():
            v = getattr(data, pn)
            if isinstance(v, Reference):
                v, document, reference_url, nreferences = _resolve_ref(
                    v.ref,
                    root=root,
                    url=url,
                    open_function=open_function,
                    references=references
                )
                if nreferences != references:
                    references = nreferences
                    v = resolve_references(
                        v,
                        root=document,
                        open_function=open_function,
                        url=reference_url,
                        references=references
                    )
                    setattr(data, pn, v)
            else:
                v = resolve_references(
                    v,
                    root=root,
                    open_function=open_function,
                    url=url,
                    references=references
                )
                setattr(data, pn, v)
    elif isinstance(data, dict):
        if ('$ref' in data.keys()) and (data is not root):
            ref = data['$ref']
            data, document, reference_url, nreferences = _resolve_ref(
                ref,
                root=root,
                url=url,
                open_function=open_function,
                references=references
            )
            if nreferences != references:
                references = nreferences
                data = resolve_references(
                    data,
                    root=document,
                    open_function=open_function,
                    url=reference_url,
                    references=references
                )
        else:
            for k, v in data.items():
                data[k] = resolve_references(
                    v,
                    root=root,
                    open_function=open_function,
                    url=url,
                    references=references
                )
    elif isinstance(data, (Set, Sequence)) and not isinstance(data, (str, bytes)):
        for i in range(len(data)):
            data[i] = resolve_references(
                data[i], root=root, open_function=open_function, url=url, references=references
            )
    return data


def loads(data):
    if isinstance(data, IOBase):
        try:
            data.seek(0)
        except UnsupportedOperation:
            pass
        if hasattr(data, 'readall'):
            data = data.readall()
        else:
            data = data.read()
    if isinstance(data, bytes):
        data = str(data, encoding='utf-8')
    if isinstance(data, str):
        try:
            data = json.loads(data, object_hook=OrderedDict)
        except json.JSONDecodeError as e:
            data = yaml.load(data)
    return data


class Object(object):

    _properties = None  # type: Optional[typing.Mapping[str, Property]]
    _url = None  # type: Optional[str]

    def __init__(
        self,
        _=None,  # type: Optional[Union[AnyStr, typing.Mapping, typing.Sequence, typing.IO]]
    ):
        if _ is not None:
            if isinstance(_, HTTPResponse):
                self._url = _.url
            _ = loads(_)
            for k, v in _.items():
                try:
                    self[k] = v
                except KeyError as e:
                    if e.args and len(e.args) == 1:
                        e.args = (
                            r'%s.%s: %s' % (type(self).__name__, e.args[0], json.dumps(_)),
                        )
                    raise e

    def __setattr__(self, property_name, value):
        # type: (Object, str, Any) -> NoneType
        if property_name[0] != '_':
            property_definition = get_property_definition(self, property_name)
            try:
                value = property_definition.load(value)
            except TypeError as e:
                message = '%s.%s: ' % (
                    self.__class__.__name__,
                    property_name
                )
                if e.args:
                    e.args = tuple(
                        chain(
                            (message + e.args[0],),
                            e.args[1:]
                        )
                    )
                else:
                    e.args = (message + repr(value),)
                raise e
        super().__setattr__(property_name, value)

    def __setitem__(self, key, value):
        # type: (str, str) -> None
        try:
            property_definition = get_property_definition(self, key)
            property_name = key
        except KeyError:
            property_definition = None
            property_name = None
            for pn, pd in get_property_definitions(self).items():
                if key == pd.name:
                    property_name = pn
                    property_definition = pd
                    break
            if property_name is None:
                raise KeyError(
                    '`%s` has no property mapped to the name "%s"' % (
                        self.__class__.__name__,
                        key
                    )
                )
        if (
            (value is None) and
            property_definition.required and
            (
                NoneType not in (
                    property_definition.types(value)
                    if isinstance(property_definition.types, Callable)
                    else property_definition.types
                )
            )
        ):
            raise ValidationError(
                'The property `%s` is required for `oapi.model.%s.%s`.' % (
                    property_name,
                    self.__class__.__name__
                )
            )
        try:
            setattr(self, property_name, value)
        except TypeError as e:
            e.args = tuple(chain(
                (
                    '`%s.%s`: %s' % (
                        self.__class__.__name__,
                        property_name,
                        e.args[0] if e else ''
                    ),
                ),
                e.args[1:] if e.args else tuple()
            ))
            raise e
        return None

    def __getitem__(self, key):
        # type: (str, str) -> None
        try:
            property_definition = get_property_definition(self, key)
            property_name = key
        except KeyError as e:
            property_definition = None
            property_name = None
            for pn, pd in get_property_definitions(self).items():
                if key == pd.name:
                    property_name = pn
                    property_definition = pd
                    break
            if property_definition is None:
                raise KeyError(
                    '`%s` has no property mapped to the name "%s"' % (
                        self.__class__.__name__,
                        key
                    )
                )
        return getattr(self, property_name)

    def __copy__(self):
        property_definitions = get_property_definitions(self)
        new_instance = self.__class__()
        set_property_definitions(
            new_instance,
            property_definitions
        )
        for k in property_definitions.keys():
            try:
                setattr(new_instance, k, getattr(self, k))
            except TypeError as e:
                label = '%s.%s: ' % (self.__class__.__name__, k)
                if e.args:
                    e.args = tuple(
                        chain(
                            (label + e.args[0],),
                            e.args[1:]
                        )
                    )
                else:
                    e.args = (label + dumps(self),)
                raise e
        new_instance._url = self._url
        return new_instance

    def __deepcopy__(self, memo):
        # type: (dict) -> None
        new_instance = copy(self)
        for k in get_property_definitions(self).keys():
            setattr(new_instance, k, deepcopy(getattr(self, k), memo))
        return new_instance

    def _dump(self):
        data = OrderedDict()
        for pn, p in get_property_definitions(self).items():
            v = getattr(self, pn)
            if v is None:
                if p.required:
                    raise ValidationError(
                        'The property `%s` is required for `oapi.model.%s`.' % (pn, self.__class__.__name__)
                    )
            else:
                v = dump(v)
                k = p.name or pn
                if (v is None) and (p.types is not None) and (Null not in p.types):
                    raise TypeError(
                        'Null values are not allowed in `oapi.model.%s.%s`.' % (self.__class__.__name__, pn)
                    )
                data[k] = v
        return data

    def __str__(self):
        return json.dumps(dump(self))

    def __eq__(self, other):
        # type: (Any) -> bool
        if isinstance(other, self.__class__):
            # return str(self) == str(other)
            self_properties = set(get_property_definitions(self).keys())
            other_properties = set(get_property_definitions(other).keys())
            if self_properties != other_properties:
                # print('%s != %s' % (repr(self_properties), repr(other_properties)))
                return False
            for p in self_properties|other_properties:
                sp = getattr(self, p)
                op = getattr(other, p)
                if sp != op:
                    # print('%s(%s)\n!=\n%s(%s)\n\n' % (type(sp).__name__, dumps(sp), type(op).__name__, dumps(op)))
                    return False
            return True
        else:
            return False

    def __ne__(self, other):
        # type: (Any) -> bool
        return False if self == other else True

    def __iter__(self):
        for k in get_property_definitions(self).keys():
            yield k


class Array(list):

    def __init__(
        self,
        items=None,  # type: Optional[Union[Sequence, Set]]
        item_types=None,  # type: Optional[Union[Sequence[Union[type, properties.Property]], type, properties.Property]]
    ):
        if isinstance(items, (str, bytes)):
            raise TypeError(
                'Array items must be a set or sequence, not `%s`:\n%s' % (
                    type(items).__name__,
                    repr(items)
                )
            )
        if isinstance(item_types, (type, properties.Property)):
            item_types = (item_types,)
        self.item_types = item_types
        for item in items:
            self.append(item)
        if items:
            super().__init__(
                properties.polymorph(item, self.item_types)
                for item in items
            )

    def __setitem__(
        self,
        index,  # type: int
        value,  # type: Any
    ):
        super().__setitem__(index, properties.polymorph(value, self.item_types))

    def append(self, value):
        # type: (Any) -> None
        super().append(properties.polymorph(value, self.item_types))

    def __copy__(self):
        # type: (Array) -> Array
        return self.__class__(tuple(self[:]), item_types=self.item_types)

    def __deepcopy__(self, memo):
        # type: (dict) -> Array
        return self.__class__(tuple(deepcopy(i, memo) for i in self[:]), item_types=self.item_types)

    def _dump(self):
        return tuple(
            dump(i) for i in self
        )




class Dictionary(OrderedDict):

    def __init__(
        self,
        items=None,  # type: Optional[typing.Mapping]
        value_types=None,  # type: Optional[Union[Sequence[Union[type, properties.Property]], type, properties.Property]]
    ):
        if isinstance(value_types, (type, properties.Property)):
            value_types = (value_types,)
        self.value_types = value_types
        if items is not None:
            # if isinstance(items, Mapping):
            #     items = tuple(items.items())
            # for k, v in items:
            #     self[k] = v
            if items is None:
                super().__init__()
            else:
                super().__init__(items)

    def __setitem__(
        self,
        key,  # type: int
        value,  # type: Any
    ):
        super().__setitem__(key, properties.polymorph(value, self.value_types))

    def __copy__(self):
        # type: (Dictionary) -> Dictionary
        return self.__class__(self.items(), value_types=self.value_types)

    def __deepcopy__(self, memo):
        # type: (dict) -> Dictionary
        return self.__class__(
            [
                (k, deepcopy(v, memo)) for k, v in self.items()
            ],
            value_types=self.value_types
        )

    def _dump(self):
        return OrderedDict(
            [
                (k, dump(v)) for k, v in self.items()
            ]
        )


class Reference(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        ref=None,  # type: Optional[str]
    ):
        self.ref = ref
        super().__init__(_)


set_property_definitions(
    Reference,
    [
        ('ref', properties.String(name='$ref'))
    ]
)


class Contact(Object):
    """
    https://swagger.io/specification/#contactObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        name=None,  # type: Optional[str]
        url=None,  # type: Optional[str]
        email=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self.name = name
        self.url = url
        self.email = email
        super().__init__(_)


set_property_definitions(
    Contact,
    [
        ('name', properties.String()),
        ('url', properties.String()),
        ('email', properties.String()),
    ]
)


class License(Object):
    """
    https://swagger.io/specification/#licenseObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        name=None,  # type: Optional[str]
        url=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self.name = name
        self.url = url
        super().__init__(_)


set_property_definitions(
    License,
    [
        ('name', properties.String()),
        ('url', properties.String()),
    ]
)


class Info(Object):
    """
    https://swagger.io/specification/#infoObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        title=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        terms_of_service=None,  # type: Optional[str]
        contact=None,  # type: Optional[Contact]
        license=None,  # type: Optional[License]
        version=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self.title = title
        self.description = description
        self.terms_of_service = terms_of_service
        self.contact = contact
        self.license = license
        self.version = version
        super().__init__(_)


set_property_definitions(
    Info,
    [
        ('title', properties.String()),
        ('description', properties.String()),
        ('terms_of_service', properties.String(name='termsOfService')),
        ('contact', properties.Object(types=(Contact,))),
        ('license', properties.Object(types=(License,))),
        ('version', properties.String()),
    ]
)


class Tag(Object):
    """
    https://swagger.io/specification/#tagObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        name=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
    ):
        # type: (...) -> None
        self.name = name
        self.description = description
        super().__init__(_)


set_property_definitions(
    Tag,
    [
        ('name', properties.String()),
        ('description', properties.String()),
    ]
)


class Link(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        rel=None,  # type: Optional[str]
        href=None,  # type: Optional[str]
    ):
        self.rel = rel
        self.href = href
        super().__init__(_)


set_property_definitions(
    Link,
    [
        ('rel', properties.String()),
        ('href', properties.String()),
    ]
)


class Schema(Object):
    """
    https://swagger.io/specification/#schemaObject
    http://json-schema.org

    Properties:

        - title (str)

        - description (str)

        - multiple_of (Number): The numeric value this schema describes should be divisible by this number.

        - maximum (Number): The number this schema describes should be less than or equal to this value, or less than
          this value, depending on the value of ``exclusive_maximum``.

        - exclusive_maximum (bool): If ``True``, the numeric instance described by this schema must be *less than*
          ``maximum``. If ``False``, the numeric instance described by this schema can be less than or *equal to*
          ``maximum``.

        - minimum (Number): The number this schema describes should be greater than or equal to this value, or greater
          than this value, depending on the value of ``exclusive_minimum``.

        - exclusive_minimum (bool): If ``True``, the numeric instance described by this schema must be *greater than*
          ``minimum``. If ``False``, the numeric instance described by this schema can be greater than or *equal to*
          ``minimum``.

        - max_length (int): The number of characters in the string instance described by this schema must be less than,
          or equal to, the value of this property.

        - min_length (int): The number of characters in the string instance described by this schema must be greater
          than, or equal to, the value of this property.

        - pattern (str): The string instance described by this schema should match this regular expression (ECMA 262).

        - items (Schema|[Schema]):

            - If ``items`` is a sub-schema—each item in the array instance described by this schema should be valid as
              described by this sub-schema.

            - If ``items`` is a sequence of sub-schemas, the array instance described by this schema should be equal in
              length to this sequence, and each value should be valid as described by the sub-schema at the
              corresponding index within this sequence of sub-schemas.

        - additional_items (Schema|bool): If ``additional_items`` is ``True``—the array instance described by
          this schema may contain additional values beyond those defined in ``items``.

        - max_items (int): The array instance described by this schema should contain no more than this number of
          items.

        - min_items (int): The array instance described by this schema should contain at least this number of
          items.

        - unique_items (bool): The array instance described by this schema should contain only unique items.

        - max_properties (int)

        - min_properties (int)

        - properties ({str:Schema}): Any properties of the object instance described by this schema which
          correspond to a name in this mapping should be valid as described by the sub-schema corresponding to that name.

        - pattern_properties (Schema): Any properties of the object instance described by this schema which
          match a name in this mapping, when the name is evaluated as a regular expression, should be valid as described by
          the sub-schema corresponding to the matched name.

        - additional_properties (bool|Schema):

            - If ``additional_properties`` is ``True``—properties may be present in the object described by
              this schema with names which do not match those in either ``properties`` or ``pattern_properties``.

            - If ``additional_properties`` is ``False``—all properties present in the object described by this schema
              must correspond to a property matched in either ``properties`` or ``pattern_properties``.

        - dependencies ({str:{str:Schema|[str]}}):

            A dictionary mapping properties of the object instance described by this schema to a mapping other
            properties and either:

                - A sub-schema for validation of the second property when the first property is present on
                  the object instance described by this schema.
                - A list of properties which must *also* be present when the first and second properties are present on
                  the object instance described by this schema.

        - enum ([Any]): The value/instance described by this schema should be among those in this sequence.

        - data_type (str|[str]): The value/instance described by this schema should be of the value_types indicated
          (if this is a string), or *one of* the value_types indicated (if this is a sequence).

            - "null"
            - "boolean"
            - "object"
            - "array"
            - "number"
            - "string"

        - format (str|[str]):

            - "date-time": A date and time in the format YYYY-MM-DDThh:mm:ss.sTZD (eg 1997-07-16T19:20:30.45+01:00),
              YYYY-MM-DDThh:mm:ssTZD (eg 1997-07-16T19:20:30+01:00), or YYYY-MM-DDThh:mmTZD (eg 1997-07-16T19:20+01:00).
            - "email"
            - "hostname"
            - "ipv4"
            - "ipv6"
            - "uri"
            - "uriref": A URI or a relative reference.

        - all_of ([Schema]): The value/instance described by the schema should *also* be valid as
          described by all sub-schemas in this sequence.

        - any_of ([Schema]): The value/instance described by the schema should *also* be valid as
          described in at least one of the sub-schemas in this sequence.

        - one_of ([Schema]): The value/instance described by the schema should *also* be valid as
          described in one (but *only* one) of the sub-schemas in this sequence.

        - is_not (Schema): The value/instance described by this schema should *not* be valid as described by this
          sub-schema.

        - definitions ({str:Schema}): A dictionary of sub-schemas, stored for the purpose of referencing
          these sub-schemas elsewhere in the schema.

        - required ([str]): A list of attributes which must be present on the object instance described by this
          schema.

        - default (Any): The value presumed if the value/instance described by this schema is absent.

        The following properties are specific to OpenAPI (not part of the core `JSON Schema <http://json-schema.org>`):

        - nullable (bool): If ``True``, the value/instance described by this schema may be a null value (``None``).

        - discriminator (Discriminator): Adds support for polymorphism.

        - read_only (bool): If ``True``, the property described may be returned as part of a response, but should not
          be part of a request.

        - write_only (bool): If ``True``, the property described may be sent as part of a request, but should not
          be returned as part of a response.

        - xml (XML): Provides additional information describing XML representation of the property described by this
          schema.

        - external_docs (ExternalDocumentation)

        - example (Any)

        - definitions (Any)

        - depracated (bool): If ``True``, the property or instance described by this schema should be phased out, as
          if will no longer be supported in future versions.
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        schema=None,  # type: Optional[str]
        schema_id=None,  # type: Optional[str]
        title=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        multiple_of=None,  # type: Optional[Number]
        maximum=None,  # type: Optional[Number]
        exclusive_maximum=None,  # type: Optional[bool]
        minimum=None,  # type: Optional[Number]
        exclusive_minimum=None,  # type: Optional[bool]
        max_length=None,  # type: Optional[int]
        min_length=None,  # type: Optional[int]
        pattern=None,  # type: Optional[str]
        items=None,  # type: Optional[Schema, Sequence[Schema]]
        additional_items=None,  # type: Optional[Schema, bool]
        max_items=None,  # type: Optional[int]
        min_items=None,  # type: Optional[int]
        unique_items=None,  # type: Optional[bool]
        max_properties=None,  # type: Optional[int]
        min_properties=None,  # type: Optional[int]
        properties=None,  # type: Optional[typing.Mapping[str, Schema]]
        pattern_properties=None,  # type: Optional[Schema]
        additional_properties=None,  # type: Optional[bool, Schema]
        dependencies=None,  # type: Optional[typing.Mapping[str, typing.Mapping[str, Union[Schema, Sequence[str]]]]]
        enum=None,  # type: Optional[Sequence]
        data_type=None,  # type: Optional[str, Sequence]
        format=None,  # type: Optional[str, Sequence]
        all_of=None,  # type: Optional[Sequence[Schema]]
        any_of=None,  # type: Optional[Sequence[Schema]]
        one_of=None,  # type: Optional[Sequence[Schema]]
        is_not=None,  # type: Optional[Schema]
        definitions=None,  # type: Optional[typing.Mapping[Schema]]
        required=None,  # type: Optional[Sequence[str]]
        default=None,  # type: Optional[Any]
        discriminator=None,  # type: Optional[Discriminator]
        read_only=None,  # type: Optional[bool]
        write_only=None,  # type: Optional[bool]
        xml=None,  # type: Optional[XML]
        external_docs=None,  # type: Optional[ExternalDocumentation]
        example=None,  # type: Any
        deprecated=None,  # type: Optional[bool]
        links=None,  # type: Optional[Sequence[Link]]
    ):
        self.schema = schema
        self.schema_id = schema_id
        self.title = title
        self.description = description
        self.multiple_of = multiple_of
        self.maximum = maximum
        self.exclusive_maximum = exclusive_maximum
        self.minimum = minimum
        self.exclusive_minimum = exclusive_minimum
        self.max_length = max_length
        self.min_length = min_length
        self.pattern = pattern
        self.items = items
        self.additional_items = additional_items
        self.max_items = max_items
        self.min_items = min_items
        self.unique_items = unique_items
        self.max_properties = max_properties
        self.min_properties = min_properties
        self.properties = properties
        self.pattern_properties = pattern_properties
        self.additional_properties = additional_properties
        self.dependencies = dependencies
        self.enum = enum
        self.data_type = data_type
        self.format = format
        self.all_of = all_of
        self.any_of = any_of
        self.one_of = one_of
        self.is_not = is_not
        self.definitions = definitions
        self.required = required
        self.default = default
        self.discriminator = discriminator
        self.read_only = read_only
        self.write_only = write_only
        self.xml = xml
        self.external_docs = external_docs
        self.example = example
        self.deprecated = deprecated
        self.links = links
        super().__init__(_)
        

# ...definitions are postponed until dependencies are defined


class Example(Object):
    """
    https://swagger.io/specification/#exampleObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        summary=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        value=None,  # type: Any
        external_value=None,  # type: Optional[str]
    ):
        self.summary = summary
        self.description = description
        self.value = value
        self.external_value = external_value
        super().__init__(_)


set_property_definitions(
    Example,
    [
        ('summary', properties.String()),
        ('description', properties.String()),
        ('value', properties.Property()),
        ('external_value', properties.String(name='externalValue')),
    ]
)


class Encoding(Object):

    """
    https://swagger.io/specification/#encodingObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        content_type=None,  # type: Optional[str]
        headers=None,  # type: Optional[typing.Mapping[str, Union[Header, Reference]]]
        style=None,  # type: Optional[str]
        explode=None,  # type: Optional[bool]
        allow_reserved=None,  # type: Optional[bool]
    ):
        self.content_type = content_type
        self.headers = headers
        self.style = style
        self.explode = explode
        self.allow_reserved = allow_reserved
        super().__init__(_)


# ...definitions for `Encoding` are delayed until after the `Headers` definition


class MediaType(Object):
    """
    https://swagger.io/specification/#mediaTypeObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        schema=None,  # type: Optional[Schema, Reference]
        example=None,  # type: Any
        examples=None,  # type: Union[typing.Mapping[str, Union[Example, Reference]]]
        encoding=None,  # type: Union[typing.Mapping[str, Union[Encoding, Reference]]]
    ):
        self.schema = schema
        self.example = example
        self.examples = examples
        self.encoding = encoding
        super().__init__(_)


set_property_definitions(
    MediaType,
    [
        ('schema', properties.Object(types=(Reference, Schema))),
        ('example', properties.Property()),
        ('examples', properties.Object(value_types=(Reference, Example))),
        ('encoding', properties.Object(value_types=(Reference, Encoding))),
    ]
)


class Header(Object):
    """
    https://swagger.io/specification/#headerObject

     Properties:

         - description (str)

         - required (bool)

         - deprecated (bool)

         - allow_empty_value (bool): Sets the ability to pass empty-valued parameters. This is valid only for query
           parameters and allows sending a parameter with an empty value. The default value is ``False``. If ``style``
           is used, and if ``behavior`` is inapplicable (cannot be serialized), the value of ``allow_empty_value`` will
           be ignored.

         - style (str): Describes how the parameter value will be serialized, depending on the type of the parameter
           value.

             - "matrix": Path-style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.7>`.
             - "label": Label-style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.5>`.
             - "form": Form style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.8>`.
             - "simple": Simple style parameters defined by
               `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.2>`.
             - "spaceDelimited": Space separated array values.
             - "pipeDelimited": Pipe separated array values.
             - "deepObject": Provides a simple way of rendering nested objects using form parameters.

           Default values (based on value of ``location``):

             - query: "form"
             - path: "simple"
             - header: "simple"
             - cookie: "form"

           https://swagger.io/specification/#style-values-52

         - explode (bool): When this is ``True``, array or object parameter values generate separate parameters for
           each value of the array or name-value pair of the map. For other value_types of parameters this property has no
           effect. When ``style`` is "form", the default value is ``True``. For all other styles, the default value is
           ``False``.

         - allow_reserved (bool): Determines whether the parameter value SHOULD allow reserved characters
           :/?#[]@!$&'()*+,;= (as defined by `RFC3986 <https://tools.ietf.org/html/rfc3986#section-2.2>`) to be included
           without percent-encoding. This property only applies to parameters with a location value of "query". The
           default value is ``False``.

         - schema (Schema): The schema defining the type used for the parameter.

         - example (Any): Example of the media type. The example should match the specified schema and encoding
           properties if present. The ``example`` parameter should not be present if ``examples`` is present. If
           referencing a ``schema`` which contains an example—*this* example overrides the example provided by the
           ``schema``. To represent examples of media value_types that cannot naturally be represented in JSON or YAML, a
           string value can contain the example with escaping where necessary.

         - examples (typing.Mapping[str, Example]): Examples of the media type. Each example should contain a value in the correct
           format, as specified in the parameter encoding. The ``examples`` parameter should not be present if
           ``example`` is present. If referencing a ``schema`` which contains an example—*these* example override the
           example provided by the ``schema``. To represent examples of media value_types that cannot naturally be represented
           in JSON or YAML, a string value can contain the example with escaping where necessary.

         - content ({str:MediaType}): A map containing the representations for the parameter. The name is the media type
           and the value describing it. The map must only contain one entry.
     """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        description=None,  # type: Optional[str]
        required=None,  # type: Optional[bool]
        deprecated=None,  # type: Optional[bool]
        allow_empty_value=None,  # type: Optional[bool]
        style=None,  # type: Optional[str]
        explode=None,  # type: Optional[bool]
        allow_reserved=None,  # type: Optional[bool]
        schema=None,  # type: Optional[Schema]
        example=None,  # type: Any
        examples=None,  # type: Optional[typing.Mapping[str, Example]]
        content=None,  # type: Optional[typing.Mapping[str, MediaType]]
    ):
        self.description = description
        self.required = required
        self.deprecated = deprecated
        self.allow_empty_value = allow_empty_value
        self.style = style
        self.explode = explode
        self.allow_reserved = allow_reserved
        self.schema = schema
        self.example = example
        self.examples = examples
        self.content = content
        super().__init__(_)


set_property_definitions(
    Encoding,
    [
        ('content_type', properties.String(name='contentType')),
        ('headers', properties.Object(value_types=(Reference, Header))),
        ('style', properties.String()),
        ('explode', properties.Boolean()),
        ('allow_reserved', properties.Boolean(name='allowReserved')),
    ]
)


set_property_definitions(
    Header,
    [
        ('description', properties.String()),
        ('required', properties.Boolean()),
        ('deprecated', properties.Boolean()),
        ('allow_empty_value', properties.Boolean(name='allowEmptyValue')),
        ('style', properties.String()),
        ('explode', properties.Boolean()),
        ('allow_reserved', properties.Boolean(name='allowReserved')),
        ('schema', properties.Object(types=(Schema,))),
        ('example', properties.Property()),
        ('examples', properties.Object(value_types=(Example,))),
        ('content', properties.Object(value_types=(MediaType,))),
    ]
)


class Parameter(Object):
    """
    https://swagger.io/specification/#parameterObject

    Properties:

        - name (str)

        - parameter_in (str):

            - "path"
            - "query"
            - "header"
            - "cookie"

        - description (str)

        - required (bool)

        - deprecated (bool)

        - allow_empty_value (bool): Sets the ability to pass empty-valued parameters. This is valid only for query
          parameters and allows sending a parameter with an empty value. The default value is ``False``. If ``style``
          is used, and if ``behavior`` is inapplicable (cannot be serialized), the value of ``allow_empty_value`` will
          be ignored.

        - style (str): Describes how the parameter value will be serialized, depending on the type of the parameter
          value.

            - "matrix": Path-style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.7>`.
            - "label": Label-style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.5>`.
            - "form": Form style parameters defined by `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.8>`.
            - "simple": Simple style parameters defined by
              `RFC6570 <https://tools.ietf.org/html/rfc6570#section-3.2.2>`.
            - "spaceDelimited": Space separated array values.
            - "pipeDelimited": Pipe separated array values.
            - "deepObject": Provides a simple way of rendering nested objects using form parameters.

          Default values (based on value of ``location``):

            - query: "form"
            - path: "simple"
            - header: "simple"
            - cookie: "form"

          https://swagger.io/specification/#style-values-52

        - explode (bool): When this is ``True``, array or object parameter values generate separate parameters for
          each value of the array or name-value pair of the map. For other value_types of parameters this property has no
          effect. When ``style`` is "form", the default value is ``True``. For all other styles, the default value is
          ``False``.

        - allow_reserved (bool): Determines whether the parameter value SHOULD allow reserved characters
          :/?#[]@!$&'()*+,;= (as defined by `RFC3986 <https://tools.ietf.org/html/rfc3986#section-2.2>`) to be included
          without percent-encoding. This property only applies to parameters with a location value of "query". The
          default value is ``False``.

        - schema (Schema): The schema defining the type used for the parameter.

        - example (Any): Example of the media type. The example should match the specified schema and encoding
          properties if present. The ``example`` parameter should not be present if ``examples`` is present. If
          referencing a ``schema`` which contains an example—*this* example overrides the example provided by the
          ``schema``. To represent examples of media value_types that cannot naturally be represented in JSON or YAML, a
          string value can contain the example with escaping where necessary.

        - examples ({str:Example}): Examples of the media type. Each example should contain a value in the correct
          format, as specified in the parameter encoding. The ``examples`` parameter should not be present if
          ``example`` is present. If referencing a ``schema`` which contains an example—*these* example override the
          example provided by the ``schema``. To represent examples of media value_types that cannot naturally be represented
          in JSON or YAML, a string value can contain the example with escaping where necessary.

        - content ({str:MediaType}): A map containing the representations for the parameter. The name is the media type
          and the value describing it. The map must only contain one entry.

    ...for version 2x compatibility:

        - data_type (str)

        - enum ([Any])
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        name=None,  # type: Optional[str]
        parameter_in=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        required=None,  # type: Optional[bool]
        deprecated=None,  # type: Optional[bool]
        allow_empty_value=None, # type: Optional[bool]
        style=None,  # type: Optional[str]
        explode=None, # type: Optional[bool]
        allow_reserved=None, # type: Optional[bool]
        schema=None, # type: Optional[Schema]
        example=None, # type: Any
        examples=None, # type: Optional[typing.Mapping[str, Example]]
        content=None,  # type: Optional[typing.Mapping[str, MediaType]]
        # 2x compatibility
        data_type=None,  # type: Optional[str]
        enum=None,  # type: Optional[Sequence[str]]
    ):
        self.name = name
        self.parameter_in = parameter_in
        self.description = description
        self.required = required
        self.deprecated = deprecated
        self.allow_empty_value = allow_empty_value
        self.style = style
        self.explode = explode
        self.allow_reserved = allow_reserved
        self.schema = schema
        self.example = example
        self.examples = examples
        self.content = content
        # 2x compatibility
        self.data_type = data_type
        self.enum = enum
        super().__init__(_)


set_property_definitions(
    Parameter,
    [
        ('name', properties.String()),
        ('parameter_in', properties.String(name='in')),
        ('description', properties.String()),
        ('required', properties.Boolean()),
        ('deprecated', properties.Boolean()),
        ('allow_empty_value', properties.Boolean()),
        ('style', properties.String()),
        ('explode', properties.Boolean()),
        ('allow_reserved', properties.Boolean()),
        ('schema', properties.Object(types=(Reference, Schema))),
        ('example', properties.Property()),
        ('examples', properties.Object(types=(Reference, Schema))),
        ('content', properties.Object(types=(MediaType,))),
        # version 2x compatibility
        (
            'data_type',
            properties.Property(
                types=(
                    properties.Array(
                        item_types=(str,)
                    ),
                    str,
                ),
                name='type'
            )
        ),
        ('enum', properties.Array()),
    ]
)


class ServerVariable(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        enum=None,  # type: Optional[Sequence[str]]
        default=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
    ):
        self.enum = enum
        self.default = default
        self.description = description
        super().__init__(_)


set_property_definitions(
    ServerVariable,
    [
        ('enum', properties.Array(item_types=(str,))),
        ('default', properties.String()),
        ('description', properties.String()),
    ]
)


class Server(Object):
    """
    https://swagger.io/specification/#serverObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        url=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        variables=None  # type: Optional[typing.Mapping[str, ServerVariable]]
    ):
        # type: (...) -> None
        self.url = url
        self.description = description
        self.variables = variables
        super().__init__(_)


set_property_definitions(
    Server,
    [
        ('url', properties.String()),
        ('description', properties.String()),
        ('variables', properties.Object(value_types=(ServerVariable,))),
    ]
)


class LinkedOperation(Object):
    """
    https://swagger.io/specification/#linkObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        operation_ref=None,  # type: Optional[str]
        operation_id=None,  # type: Optional[str]
        parameters=None,  # type: Optional[typing.Mapping[str, Any]]
        request_body=None,  # type: Any
        description=None,  # type: Optional[str]
        server=None,  # type: Optional[Server]
    ):
        self.operation_ref = operation_ref
        self.operation_id = operation_id
        self.parameters = parameters
        self.request_body = request_body
        self.description = description
        self.server = server
        super().__init__(_)


set_property_definitions(
    LinkedOperation,
    [
        ('operation_ref', properties.String(name='operationRef')),
        ('operation_id', properties.String(name='operationId')),
        ('parameters', properties.Object(value_types=(str,))),
        ('request_body', properties.Property(name='requestBody')),
        ('description', properties.String()),
        ('server', properties.Object(types=(Server,))),
    ]
)


class Response(Object):
    """
    https://swagger.io/specification/#responseObject

    Properties:

        - description (str): A short description of the response. `CommonMark syntax<http://spec.commonmark.org/>` may
          be used for rich text representation.

        - headers ({str:Header|Reference}): Maps a header name to its definition (mappings are case-insensitive).

        - content ({str:Content|Reference}): A mapping of media value_types to ``MediaType`` instances describing potential
          payloads.

        - links ({str:LinkedOperation|Reference}): A map of operations links that can be followed from the response.
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        description=None,  # type: Optional[str]
        headers=None,  # type: Optional[typing.Mapping[str, Union[Header, Reference]]]
        content=None,  # type: Optional[typing.Mapping[str, Union[Content, Reference]]]
        links=None,  # type: Optional[typing.Mapping[str, Union[Link, Reference]]]
    ):
        # type: (...) -> None
        self.description = description
        self.headers = headers
        self.content = content
        self.links = links
        super().__init__(_)


set_property_definitions(
    Response,
    [
        ('description', properties.String()),
        ('headers', properties.Object(value_types=(Reference, Header))),
        ('content', properties.Object(value_types=(Reference, MediaType))),
        ('links', properties.Object(value_types=(Reference, Link))),
    ]
)


class ExternalDocumentation(Object):
    """
    Properties:

        - description (str)
        - url (str)
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        description=None,  # type: Optional[str]
        url=None,  # type: Optional[str]
    ):
        self.description = description
        self.url = url
        super().__init__(_)


set_property_definitions(
    ExternalDocumentation,
    [
        ('description', properties.String()),
        ('url', properties.String()),
    ]
)


class RequestBody(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        description=None,  # type: Optional[str]
        content=None,  # type: Optional[typing.Mapping[str, MediaType]]
        required=None,  # type: Optional[bool]
    ):
        self.description = description
        self.content = content
        self.required = required
        super().__init__(_)


set_property_definitions(
    RequestBody,
    [
        ('description', properties.String()),
        ('content', properties.Object(value_types=(MediaType,))),
        ('required', properties.Boolean()),
    ]
)


class Operation(Object):
    """
    https://swagger.io/specification/#operationObject

    Describes a single API operation on a path.

    Properties:

        - tags (Sequence[str]):  A list of tags for API documentation control. Tags can be used for logical grouping of
          operations by resources or any other qualifier.

        - summary (str):  A short summary of what the operation does.

        - description (str): A verbose explanation of the operation behavior. `CommonMark <http://spec.commonmark.org>`
          syntax may be used for rich text representation.

        - external_docs (ExternalDocumentation):  Additional external documentation for this operation.

        - operation_id (str):  Unique string used to identify the operation. The ID must be unique among all operations
          described in the API. Tools and libraries may use the ``operation_id`` to uniquely identify an operation,
          therefore, it is recommended to follow common programming naming conventions.

        - parameters ([Parameter|Reference]):  A list of parameters that are applicable for this operation. If a
          parameter is already defined at the ``PathItem``, the new definition will override it, but can never remove
          it.

        - request_body (RequestBody|Reference):  The request body applicable for this operation. The requestBody is only
          supported in HTTP methods where the HTTP 1.1 specification
          `RFC7231 <https://tools.ietf.org/html/rfc7231#section-4.3.1>` has explicitly defined semantics for request
          bodies.

        - responses (typing.Mapping[str, Response]):  A mapping of HTTP response codes to response schemas.

        - callbacks ({str:{str:PathItem}|Reference})

        - deprecated (bool)

        - security ([[str]])

        - servers ([Server])

    Version 2x Compatibility:

        - produces ([str]):
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        tags=None,  # type: Optional[Sequence[str]]
        summary=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        external_docs=None,  # type: Optional[ExternalDocumentation]
        operation_id=None,  # type: Optional[str]
        parameters=None,  # type: Optional[Sequence[Union[Parameter, Reference]]]
        request_body=None,  # type: Optional[RequestBody, Reference]
        deprecated=None,  # type: Optional[bool]
        responses=None,  # type: Optional[typing.Mapping[str, Response]]
        callbacks=None,  # type: Optional[typing.Mapping[str, Union[Callback, Refefence]]]
        security=None,  # type: Optional[Sequence[[str]]]
        servers=None,  # type: Optional[Sequence[Server]]
        # Version 2x Compatibility
        produces=None,  # type: Optional[Sequence[str]]
    ):
        # type: (...) -> None
        self.tags = tags
        self.summary = summary
        self.description = description
        self.external_docs = external_docs
        self.operation_id = operation_id
        self.parameters = parameters
        self.request_body = request_body
        self.responses = responses
        self.deprecated = deprecated
        self.callbacks = callbacks
        self.security = security
        self.servers = servers
        # Version 2x Compatibility
        self.produces = produces
        super().__init__(_)


# Property definitions for `Operation` deferred until after `PathItem` is defined


class PathItem(Object):
    """
    https://swagger.io/specification/#pathItemObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        ref=None,  # type: Optional[str]
        summary=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        get=None,  # type: Optional[Operation]
        put=None,  # type: Optional[Operation]
        post=None,  # type: Optional[Operation]
        delete=None,  # type: Optional[Operation]
        options=None,  # type: Optional[Operation]
        head=None,  # type: Optional[Operation]
        patch=None,  # type: Optional[Operation]
        trace=None,  # type: Optional[Operation]
        servers=None,  # type: Optional[Sequence[Server]]
        parameters=None,  # type: Optional[Sequence[Parameter]]
    ):
        # type: (...) -> None
        self.ref = ref
        self.summary = summary
        self.description = description
        self.get = get
        self.put = put
        self.post = post
        self.delete = delete
        self.options = options
        self.head = head
        self.patch = patch
        self.trace = trace
        self.servers = servers
        self.parameters = parameters
        super().__init__(_)


set_property_definitions(
    PathItem,
    [
        ('ref', properties.String(name='$ref')),
        ('summary', properties.String()),
        ('description', properties.String()),
        ('get', properties.Object(types=(Operation,))),
        ('put', properties.Object(types=(Operation,))),
        ('post', properties.Object(types=(Operation,))),
        ('delete', properties.Object(types=(Operation,))),
        ('options', properties.Object(types=(Operation,))),
        ('head', properties.Object(types=(Operation,))),
        ('patch', properties.Object(types=(Operation,))),
        ('trace', properties.Object(types=(Operation,))),
        ('servers', properties.Array(item_types=(Server,))),
        (
            'parameters',
            properties.Array(
                item_types=(
                    properties.Object(
                        types=(Reference, Parameter)
                    ),
                )
            )
        ),
    ]
)


set_property_definitions(
    Operation,
    [
        ('tags', properties.Array(item_types=(Tag,))),
        ('summary', properties.String()),
        ('description', properties.String()),
        ('external_docs', properties.Object(types=(ExternalDocumentation,), name='externalDocs')),
        ('operation_id', properties.String(name='operationId')),
        ('parameters', properties.Array(item_types=(Reference, Parameter))),
        ('request_body', properties.Object(types=(Reference, RequestBody), name='requestBody')),
        ('responses', properties.Object(value_types=(Response,))),
        ('deprecated', properties.Boolean()),
        (
            'security',
            properties.Array(
                item_types=(
                    properties.Object(
                        value_types=(
                            properties.Array(
                                item_types=(str,)
                            ),
                        )
                    ),
                )
            )
        ),
        ('servers', properties.Array(item_types=(Server,))),
        ('produces', properties.Array(item_types=(str,))),
        (
            'callbacks',
            properties.Object(
                value_types=(
                    properties.Object(
                        value_types=(PathItem,)
                    )
                )
            )
        )
    ]
)


class Discriminator(Object):
    """
    https://swagger.io/specification/#discriminatorObject

    Properties:

        - property_name (str): The name of the property which will hold the discriminating value.

        - mapping ({str:str}): An mappings of payload values to schema names or references.
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        property_name=None,  # type: Optional[str]
        mapping=None,  # type: Optional[typing.Mapping[str, str]]
    ):
        self.property_name = property_name
        self.mapping = mapping
        super().__init__(_)


set_property_definitions(
    Discriminator,
    [
        ('property_name', properties.String(name='propertyName')),
        ('mapping', properties.Object(value_types=(str,))),
    ]
)


class XML(Object):
    """
    https://swagger.io/specification/#xmlObject

    Properties:

        - name (str): The element name.

        - name_space (str): The *absolute* URI of a namespace.

        - prefix (str): The prefix to be used with the name to reference the name-space.

        - attribute (bool): If ``True``, the property described is an attribute rather than a sub-element.

        - wrapped (bool): If ``True``, an array instance described by the schema will be wrapped by a tag (named
          according to the parent element's property, while ``name`` refers to the child element name).
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        name=None,  # type: Optional[str]
        name_space=None,  # type: Optional[str]
        prefix=None,  # type: Optional[str]
        attribute=None,  # type: Optional[bool]
        wrapped=None,  # type: Optional[bool]
    ):
        self.name = name
        self.name_space = name_space
        self.prefix = prefix
        self.attribute = attribute
        self.wrapped = wrapped
        super().__init__(_)


set_property_definitions(
    XML,
    [
        ('name', properties.String()),
        ('name_space', properties.String(name='nameSpace')),
        ('prefix', properties.String()),
        ('attribute', properties.Boolean()),
        ('wrapped', properties.Boolean()),
    ]
)


class OAuthFlow(Object):
    """
    https://swagger.io/specification/#oauthFlowObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        authorization_url=None,  # type: Optional[str]
        token_url=None,  # type: Optional[str]
        refresh_url=None,  # type: Optional[str]
        scopes=None,  # type: Optional[typing.Mapping[str, str]]
    ):
        self.authorization_url = authorization_url
        self.token_url = token_url
        self.refresh_url = refresh_url
        self.scopes = scopes
        super().__init__(_)


set_property_definitions(
    OAuthFlow,
    [
        ('authorization_url', properties.String()),
        ('token_url', properties.String(name='tokenUrl')),
        ('refresh_url', properties.String(name='refreshUrl')),
        ('scopes', properties.Object(value_types=(str,))),
    ]
)


class OAuthFlows(Object):
    """
    https://swagger.io/specification/#oauthFlowsObject
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        implicit=None,  # type: Optional[OAuthFlow]
        password=None,  # type: Optional[OAuthFlow]
        client_credentials=None,  # type: Optional[OAuthFlow]
        authorization_code=None,  # type: Optional[OAuthFlow]
    ):
        self.implicit = implicit
        self.password = password
        self.client_credentials = client_credentials
        self.authorization_code = authorization_code
        super().__init__(_)


set_property_definitions(
    OAuthFlows,
    [
        ('implicit', properties.Object(types=(OAuthFlow,))),
        ('password', properties.Object(types=(OAuthFlow,))),
        ('client_credentials', properties.Object(types=(OAuthFlow,), name='clientCredentials')),
        ('authorization_code', properties.Object(types=(OAuthFlow,), name='authorizationCode')),
    ]
)


class SecurityScheme(Object):
    """
    https://swagger.io/specification/#requestBodyObject

    Properties:

        - security_scheme_type (str): https://tools.ietf.org/html/rfc7235#section-4

        - description (str)

        - name (str)

        - security_scheme_in (str)

        - scheme (str)

        - bearer_format (str)

        - flows (OAuthFlows)

        - open_id_connect_url (str)
    """

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        security_scheme_type=None,  # type: Optional[str]
        description=None,  # type: Optional[str]
        name=None,  # type: Optional[str]
        security_scheme_in=None,  # type: Optional[str]
        scheme=None,  # type: Optional[str]
        bearer_format=None,  # type: Optional[str]
        flows=None,  # type: Optional[OAuthFlows]
        open_id_connect_url=None,  # type: Optional[str]
    ):
        self.security_scheme_type = security_scheme_type
        self.description = description
        self.name = name
        self.security_scheme_in = security_scheme_in
        self.scheme = scheme
        self.bearer_format = bearer_format
        self.flows = flows
        self.open_id_connect_url = open_id_connect_url
        super().__init__(_)


set_property_definitions(
    SecurityScheme,
    [
        ('security_scheme_type', properties.String(name='type')),
        ('description', properties.String()),
        ('name', properties.String()),
        ('security_scheme_in', properties.String(name='in')),
        ('scheme', properties.String()),
        ('bearer_format', properties.String(name='bearerFormat')),
        ('flows', properties.Object(types=(OAuthFlows,))),
        ('open_id_connect_url', properties.String()),
    ]
)

set_property_definitions(
    Schema,
    [
        ('schema', properties.String(name='$schema')),
        ('schema_id', properties.String(name='$id')),
        ('title', properties.String()),
        ('description', properties.String()),
        ('multiple_of', properties.Number(name='multipleOf')),
        ('maximum', properties.Number()),
        ('exclusive_maximum', properties.Boolean(name='exclusiveMaximum')),
        ('minimum', properties.Number()),
        ('exclusive_minimum', properties.Boolean(name='exclusiveMinimum')),
        ('max_length', properties.Integer(name='maxLength')),
        ('min_length', properties.Integer(name='minLength')),
        ('pattern', properties.String()),
        ('max_items', properties.Integer(name='maxItems')),
        ('min_items', properties.Integer(name='minItems')),
        ('unique_items', properties.String(name='uniqueItems')),
        (
            'items',
            properties.Object(
                types=(
                    Schema,
                    Reference,
                    properties.Array(
                        item_types=(Reference, Schema)
                    )
                )
            )
        ),
        (
            'additional_items',
            properties.Object(
                types=(
                    Schema,
                    bool
                ),
                name='additionalItems'
            )
        ),
        ('max_properties', properties.Integer(name='maxProperties')),
        ('min_properties', properties.Integer(name='minProperties')),
        ('properties', properties.Object(value_types=(Schema,))),
        ('pattern_properties', properties.Object(name='patternProperties')),
        ('additional_properties', properties.Object(name='additionalProperties')),
        ('dependencies', properties.Object(types=(Schema), versions=('openapi<0.0',))),
        ('enum', properties.Array(item_types=(properties.String(),))),
        (
            'data_type',
            properties.Property(
                types=(
                    properties.Array(
                        item_types=(str,)
                    ),
                    str
                ),
                name='type'
            )
        ),
        ('format', properties.String()),
        ('required', properties.Array(item_types=(properties.String(),))),
        ('all_of', properties.Array(item_types=(Reference, Schema), name='allOf')),
        ('any_of', properties.Array(item_types=(Reference, Schema), name='anyOf')),
        ('one_of', properties.Array(item_types=(Reference, Schema), name='oneOf')),
        ('is_not', properties.Object(types=(Reference, Schema), name='isNot')),
        (
            'definitions',
            properties.Object(
                value_types=(
                    Schema, Response, Parameter, Example, RequestBody, Header,
                    SecurityScheme, LinkedOperation, properties.Object(value_types=PathItem)
                )
            )
        ),
        ('default', properties.Property()),
        ('required', properties.Array(item_types=(str,))),
        ('default', properties.Property()),
        ('discriminator', properties.Object(types=(Discriminator,))),
        ('read_only', properties.Boolean()),
        ('write_only', properties.Boolean(name='writeOnly')),
        ('xml', properties.Object(types=(XML,), name='xml')),
        ('external_docs', properties.Object(types=(ExternalDocumentation,))),
        ('example', properties.Property()),
        ('deprecated', properties.Boolean()),
        ('links', properties.Array(item_types=(Link,))),\
    ]
)


class Components(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        schemas=None,  # type: Union[typing.Mapping[str, Union[Schema, Reference]]]
        responses=None,  # type: Union[typing.Mapping[str, Union[Response, Reference]]]
        parameters=None,  # type: Union[typing.Mapping[str, Union[Parameter, Reference]]]
        examples=None,  # type: Union[typing.Mapping[str, Union[Example, Reference]]]
        request_bodies=None,  # type: Union[typing.Mapping[str, Union[RequestBody, Reference]]]
        headers=None,  # type: Union[typing.Mapping[str, Union[Header, Reference]]]
        security_schemes=None,  # type: Union[typing.Mapping[str, Union[SecurityScheme, Reference]]]
        links=None,  # type: Union[typing.Mapping[str, Union[LinkedOperation, Reference]]]
        callbacks=None,  # type: Union[typing.Mapping[str, Union[typing.Mapping[str, PathItem], Reference]]]
    ):
        self.schemas = schemas
        self.responses = responses
        self.parameters = parameters
        self.examples = examples
        self.request_bodies = request_bodies
        self.headers = headers
        self.security_schemes = security_schemes
        self.links = links
        self.callbacks = callbacks
        super().__init__(_)


set_property_definitions(
    Components,
    [
        ('schemas', properties.Object(value_types=(Reference, Schema))),
        ('responses', properties.Object(value_types=(Reference, Response))),
        ('parameters', properties.Object(value_types=(Reference, Parameter))),
        ('examples', properties.Object(value_types=(Reference, Example))),
        ('request_bodies', properties.Object(value_types=(Reference, RequestBody))),
        ('headers', properties.Object(value_types=(Reference, Header))),
        ('security_schemes', properties.Object(value_types=(Reference, SecurityScheme), name='securitySchemes')),
        ('links', properties.Object(value_types=(Reference, LinkedOperation))),
        (
            'callbacks',
            properties.Object(
                value_types=(
                    Reference,
                    properties.Object(
                        value_types=(
                            PathItem,
                        )
                    )
                )
            )
        ),
    ]
)


class OpenAPI(Object):

    def __init__(
        self,
        _=None,  # type: Optional[typing.Mapping]
        openapi=None,  # type: Optional[str]
        info=None,  # type: Optional[Info]
        host=None,  # type: Optional[str]
        servers=None,  # type: Optional[Sequence[str]]
        base_path=None,  # type: Optional[str]
        schemes=None,  # type: Optional[Sequence[str]]
        tags=None,  # type: Optional[Sequence[Tag]]
        paths=None,  # type: Optional[typing.Mapping[str, PathItem]]
        components=None,  # type: Optional[Components]
        consumes=None,  # type: Any
        # 2.0 compatibility
        swagger=None,  # type: Optional[str]
        definitions=None,  # type: Optional[typing.Mapping[str, Object]]
        security_definitions=None,  # type: Optional[typing.Mapping[str, Union[Object, str]]]
        produces=None,  # type: Optional[typing.Collection[str]]
        external_docs=None,  # type: Optional[ExternalDocumentation]
    ):
        # type: (...) -> None
        self.openapi = openapi
        self.info = info
        self.host = host
        self.servers = servers
        self.base_path = base_path
        self.schemes = schemes
        self.tags = tags
        self.paths = paths
        self.components = components
        self.consumes = consumes
        # 2.0 compatibility
        self.swagger = swagger
        self.definitions = definitions
        self.security_definitions = security_definitions
        self.produces = produces
        self.external_docs = external_docs
        super().__init__(_)
        version = self.openapi or self.swagger
        if version is not None:
            set_version(self, 'openapi', version)


set_property_definitions(
    OpenAPI,
    [
        ('openapi', properties.String(versions=('openapi>=3.0',))),
        ('info', properties.Object(types=(Info,), required=True)),
        ('host', properties.String()),
        ('servers', properties.Array(item_types=(Server,))),
        ('base_path', properties.String(name='basePath')),
        ('schemes', properties.Array(item_types=(str,))),
        ('tags', properties.Array(item_types=(Tag,))),
        ('paths', properties.Object(value_types=(PathItem,))),
        ('components', properties.Object(types=(Components,))),
        ('consumes', properties.Array(item_types=(str,))),
        ('swagger', properties.String(versions=('openapi<3.0',))),
        (
            'definitions',
            properties.Object(
                value_types=(
                    Schema, Response, Parameter, Example, RequestBody, Header,
                    SecurityScheme, LinkedOperation, properties.Object(value_types=PathItem)
                ),
                # versions=('openapi<3.0',)
            ),
        ),
        (
            'security_definitions',
            properties.Object(
                value_types=(SecurityScheme, str),
                name='securityDefinitions',
                versions=('openapi<3.0',)
            )
        ),
        ('produces', properties.Array(item_types=(str,), versions=('openapi<3.0',)),),
        ('external_docs', properties.Object(types=(ExternalDocumentation,), name='externalDocs'))
    ]
)
