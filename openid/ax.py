"""Implements the OpenID attribute exchange specification, version 1.0
as of svn revision 295 from openid.net svn.
"""

__all__ = [
    'AttributeRequest',
    'FetchRequest',
    'FetchResponse',
    ]
from openid import extension
from openid.message import NamespaceMap

class AXError(ValueError):
    """Results from data that does not meet the attribute exchange 1.0
    specification"""

class AXMessage(extension.Extension):
    """Abstract class containing common code for attribute exchange messages

    @cvar ns_alias: The preferred namespace alias for attribute
        exchange messages

    @cvar mode: The type of this attribute exchange message. This must
        be overridden in subclasses.
    """

    # This class is abstract, so it's OK that it doesn't override the
    # abstract method in Extension:
    #
    #pylint:disable-msg=W0223

    ns_alias = 'ax'
    mode = None
    ns_uri = 'http://openid.net/srv/ax/1.0'

    def _checkMode(self, ax_args):
        """Raise an exception if the mode in the attribute exchange
        arguments does not match what is expected for this class.

        @raises ValueError: When the mode does not match
        """
        mode = ax_args.get('mode')
        if mode != self.mode:
            raise AXError(
                'Expected mode %r; got %r' % (self.mode, mode))

    def _newArgs(self):
        """Return a set of attribute exchange arguments containing the
        basic information that must be in every attribute exchange
        message.
        """
        return {'mode':self.mode}


class AttrInfo(object):
    """Represents a single attribute in an attribute exchange
    request. This should be added to an AXRequest object in order to
    request the attribute.

    @ivar required: Whether the attribute will be marked as required
        when presented to the subject of the attribute exchange
        request.
    @type required: bool

    @ivar count: How many values of this type to request from the
        subject. Defaults to one.
    @type count: int

    @ivar type_uri: The identifier that determines what the attribute
        represents and how it is serialized. For example, one type URI
        representing dates could represent a Unix timestamp in base 10
        and another could represent a human-readable string.
    @type type_uri: str

    @ivar alias: The name that should be given to this alias in the
        request. If it is not supplied, a generic name will be
        assigned. For example, if you want to call a Unix timestamp
        value 'tstamp', set its alias to that value. If two attributes
        in the same message request to use the same alias, the request
        will fail to be generated.
    @type alias: str or NoneType
    """

    # It's OK that this class doesn't have public methods (it's just a
    # holder for a bunch of attributes):
    #
    #pylint:disable-msg=R0903

    def __init__(self, type_uri, count=None, required=False, alias=None):
        self.required = required
        self.count = count
        self.type_uri = type_uri
        self.alias = alias

def toTypeURIs(namespace_map, alias_list_s):
    """Given a namespace mapping and a string containing a
    comma-separated list of namespace aliases, return a list of type
    URIs that correspond to those aliases.

    @param namespace_map: The mapping from namespace URI to alias
    @type namespace_map: openid.message.NamespaceMap

    @param alias_list_s: The string containing the comma-separated
        list of aliases. May also be None for convenience.
    @type alias_list_s: str or NoneType

    @returns: The list of namespace URIs that corresponds to the
        supplied list of aliases. If the string was zero-length or
        None, an empty list will be returned.

    @raise KeyError: If an alias is present in the list of aliases but
        is not present in the namespace map.
    """
    uris = []

    if alias_list_s:
        for alias in alias_list_s.split(','):
            type_uri = namespace_map.getNamespaceURI(alias)
            if type_uri is None:
                raise KeyError(
                    'No type is defined for attribute name %r' % (alias,))
            else:
                uris.append(type_uri)

    return uris

def parseAXValues(ax_args):
    """Parse an attribute exchange {type_uri:[value]} mapping out of a
    set of attribute exchange arguments

    @param ax_args: The unqualified attribute exchange parameters

    @returns: which types were requested without a count parameter and
        a mapping from type URI to list of (unicode) values. The
        dictionary containing the types that were requested without a
        count will only contain those values; membership in the
        dictionary is a sufficient test of whether the value was
        requested as a singleton.

    @rtype: [str], {str:[unicode]}

    @raises KeyError: When an expected value is not present in the
        source data (for example, a type alias is declared, but there
        is no count or value)
    """

    # Container for the parsed data
    data = {}

    # Which values were requested without a "count"
    singletons = []

    aliases = NamespaceMap()

    for key, value in ax_args.iteritems():
        if key.startswith('type.'):
            type_uri = value
            alias = key[5:]
            aliases.addAlias(type_uri, alias)

    for type_uri, alias in aliases.iteritems():
        try:
            count_s = ax_args['count.' + alias]
        except KeyError:
            singletons.append(type_uri)
            value = ax_args['value.' + alias]
            if value == u'':
                values = []
            else:
                values = [value]
        else:
            count = int(count_s)
            values = []
            for i in range(1, count + 1):
                value_key = 'value.%s.%d' % (alias, i)
                value = ax_args[value_key]
                values.append(value)

        data[type_uri] = values

    return singletons, data

class FetchRequest(AXMessage):
    """An attribute exchange 'fetch_request' message. This message is
    sent by a relying party when it wishes to obtain attributes about
    the subject of an OpenID authentication request.

    @ivar requested_attributes: The attributes that have been
        requested thus far, indexed by the type URI.
    @type requested_attributes: {str:AttrInfo}

    @ivar update_url: A URL that will accept responses for this
        attribute exchange request, even in the absence of the user
        who made this request.
    """
    mode = 'fetch_request'

    def __init__(self, update_url=None):
        AXMessage.__init__(self)
        self.requested_attributes = {}
        self.update_url = update_url

    def add(self, attribute):
        """Add an attribute to this attribute exchange request.

        @param attribute: The attribute that is being requested
        @type attribute: C{L{AttrInfo}}

        @returns: None

        @raise KeyError: when the requested attribute is already
            present in this fetch request.
        """
        if attribute.type_uri in self.requested_attributes:
            raise KeyError('The attribute %r has already been requested'
                           % (attribute.type_uri,))

        self.requested_attributes[attribute.type_uri] = attribute

    def getExtensionArgs(self):
        """Get the serialized form of this attribute fetch request.

        @returns: The fetch request message parameters
        @rtype: {unicode:unicode}
        """
        aliases = NamespaceMap()

        required = []
        if_available = []

        ax_args = self._newArgs()

        for type_uri, attribute in self.requested_attributes.iteritems():
            if attribute.alias is None:
                alias = aliases.add(type_uri)
            else:
                # XxXX: this will raise an exception when the second
                # attribute with the same alias is added. I think it
                # would be better to complain at the time that the
                # attribute is added to this object so that the code
                # that is adding it is identified in the stack trace,
                # but it's more work to do so, and it won't be 100%
                # accurate anyway, since the attributes are
                # mutable. So for now, just live with the fact that
                # we'll learn about the error later.
                #
                # The other possible approach is to hide the error and
                # generate a new alias on the fly. I think that would
                # probably be bad.
                alias = aliases.addAlias(type_uri, attribute.alias)

            if attribute.required:
                required.append(alias)
            else:
                if_available.append(alias)

            if attribute.count is not None:
                ax_args['count.' + alias] = str(attribute.count)

            ax_args['type.' + alias] = type_uri

        if required:
            ax_args['required'] = ','.join(required)

        if if_available:
            ax_args['if_available'] = ','.join(if_available)

        return ax_args

    def getRequiredAttrs(self):
        """Get the type URIs for all attributes that have been marked
        as required.

        @returns: A list of the type URIs for attributes that have
            been marked as required.
        @rtype: [str]
        """
        required = []
        for type_uri, attribute in self.requested_attributes.iteritems():
            if attribute.required:
                required.append(type_uri)

        return required

    def fromOpenIDRequest(cls, message):
        """Extract a FetchRequest from an OpenID message

        @param message: The OpenID message containing the attribute
            fetch request
        @type message: C{L{openid.message.Message}}

        @rtype: C{L{FetchRequest}}
        @returns: The FetchRequest extracted from the message

        @raises KeyError: if the message is not consistent in its use
            of namespace aliases.

        XXX: ValueError, too
        """
        ax_args = message.getArgs(cls.ns_uri)
        self = cls()
        self.parseExtensionArgs(ax_args)
        return self

    fromOpenIDRequest = classmethod(fromOpenIDRequest)

    def parseExtensionArgs(self, ax_args):
        """Given attribute exchange arguments, populate this FetchRequest.

        @raises KeyError: if the message is not consistent in its use
            of namespace aliases.
        XXX: ValueError, too
        """
        # Raises an exception if the mode is not the expected value
        self._checkMode(ax_args)

        aliases = NamespaceMap()

        for key, value in ax_args.iteritems():
            if key.startswith('type.'):
                alias = key[5:]
                type_uri = value
                aliases.addAlias(type_uri, alias)
                count_s = ax_args.get('count.' + alias)
                attr_req = AttrInfo(type_uri, alias=alias)

                if count_s:
                    count = int(count_s)
                else:
                    count = None
                attr_req.count = count

                self.add(attr_req)

        required = toTypeURIs(aliases, ax_args.get('required'))

        for type_uri in required:
            self.requested_attributes[type_uri].required = True

        if_available = toTypeURIs(aliases, ax_args.get('if_available'))

        all_type_uris = required + if_available

        for type_uri in aliases.iterNamespaceURIs():
            if type_uri not in all_type_uris:
                raise ValueError(
                    'Type URI %r was in the request but not '
                    'present in "required" or "if_available"' % (type_uri,))

        self.update_url = ax_args.get('update_url')

    def iterAttrs(self):
        """Iterate over the AttrInfo objects that are
        contained in this fetch_request.
        """
        return self.requested_attributes.itervalues()

    def iter(self):
        """Iterate over the attribute type URIs in this fetch_request
        """
        return iter(self.requested_attributes)

    def has_key(self, type_uri):
        """Is the given type URI present in this fetch_request?
        """
        return type_uri in self.requested_attributes

    __contains__ = has_key

class FetchResponse(AXMessage):
    """A fetch_response attribute exchange message
    """
    mode = 'fetch_response'

    def __init__(self, request=None):
        AXMessage.__init__(self)
        self.request = request
        self.data = {}
        self.update_url = None

        if request:
            for type_uri in self.request:
                self.data[type_uri] = []
            self.update_url = request.update_url

    def addValue(self, type_uri, value):
        """Add a single value for the given attribute type to the
        response. If there are already values specified for this type,
        this value will be sent in addition to the values already
        specified.

        @param type_uri: The URI for the attribute

        @param value: The value to add to the response to the relying
            party for this attribute
        @type value: unicode

        @raises KeyError: If the type_uri has not been declared to be
            in this response.

        @raises ValueError: If adding this value would exceed the
            maximum number of allowed responses for this attribute

        @returns: None
        """
        num_allowed = self.request.requested_attributes[type_uri].count
        if len(self.data[type_uri]) == num_allowed:
            raise ValueError(
                'Cannot add any more values for the attribute %r. The '
                'request asked for up to %s values.' %
                (type_uri, num_allowed,))

        self.data[type_uri].append(value)

    def setValues(self, type_uri, values):
        """Set the values for the given attribute type. This replaces
        any values that have already been set for this attribute.

        @param type_uri: The URI for the attribute

        @param values: A list of values to send for this attribute.
        @type values: [unicode]

        @raises ValueError: If the number of values specified is
            greater than the number of values allowed for this
            attribute.

        @raises KeyError: If the attribute type has not been declared
            to be in this response.

        @returns: None
        """
        num_set = len(values)
        num_allowed = self.request.requested_attributes[type_uri].count

        if num_set > num_allowed:
            raise ValueError(
                'Attempted to send more than the allowed number of values '
                'in the response for %r. Up to %s allowed, got %s' %
                (type_uri, num_allowed, num_set))

        if type_uri not in self.data:
            raise KeyError(type_uri)

        self.data[type_uri] = values

    def getExtensionArgs(self):
        """Serialize this object into arguments in the attribute
        exchange namespace

        @returns: The dictionary of unqualified attribute exchange
            arguments that represent this fetch_response.
        @rtype: {unicode;unicode}
        """
        ax_args = self._newArgs()

        if self.update_url:
            ax_args['update_url'] = self.update_url

        aliases = NamespaceMap()

        for type_uri, attr_request in \
                self.request.requested_attributes.iteritems():
            values = self.data[type_uri]
            alias = attr_request.alias
            if alias is None:
                alias = aliases.add(type_uri)
            else:
                aliases.addAlias(type_uri, alias)

            if len(values) > attr_request.count:
                raise ValueError(
                    'More than the number of requested values were '
                    'specified for %r' % (type_uri,))

            if attr_request.count is None:
                if len(values) == 0:
                    value = u''
                else:
                    (value,) = values

                ax_args['value.' + alias] = value
            else:
                for i, value in enumerate(values):
                    key = 'value.%s.%d' % (alias, i + 1)
                    ax_args[key] = value

                ax_args['count.' + alias] = str(len(values))

            ax_args['type.' + alias] = type_uri

    def fromSuccessResponse(cls, success_response, signed=True):
        """Construct a FetchResponse object from an OpenID library
        SuccessResponse object.

        @param success_response: A successful id_res response object
        @type success_response: openid.consumer.consumer.SuccessResponse

        @param signed: Whether non-signed args should be
            processsed. If True (the default), only signed arguments
            will be processsed.
        @type signed: bool

        @returns: A FetchResponse containing the data from the OpenID
            message
        """
        self = cls()
        if signed:
            ax_args = success_response.getSignedNS(self.ns_uri)
        else:
            ax_args = success_response.message.getArgs(self.ns_uri)

        self.parseExtensionArgs(ax_args)

    fromSuccessResponse = classmethod(fromSuccessResponse)

    def parseExtensionArgs(self, ax_args):
        """Parse these attrbiute exchange fetch_response arguments
        into this FetchResponse object.

        @param ax_args: The attribute exchange fetch_response
            arguments, with namespacing removed.
        @type ax_args: {unicode:unicode}

        @returns: None

        @raises ValueError: If the message has bad values for
            particular fields

        @raises KeyError: If the namespace mapping is bad or required
            arguments are missing
        """
        self._checkMode(ax_args)

        # XXX: without the request as context, we can't validate
        # whether the response's format actually matches what it
        # should. We'll just pretend that it doesn't matter, as long
        # as it's well-formed, until the spec discussion is complete.

        _, self.data = parseAXValues(ax_args)

        self.update_url = ax_args.get('update_url')

    def getSingle(self, type_uri, default=None):
        """Get a single value for an attribute. If no value was sent
        for this attribute, use the supplied default. If there is more
        than one value for this attribute, this method will fail.

        @type type_uri: str
        @param type_uri: The URI for the attribute

        @param default: The value to return if the attribute was not
            sent in the fetch_response.

        @returns: The value of the attribute in the fetch_response
            message, or the default supplied
        @rtype: unicode or NoneType

        @raises ValueError: If there is more than one value for this
            parameter in the fetch_response message.
        @raises KeyError: If the attribute was not sent in this response
        """
        values = self.data[type_uri]
        if not values:
            return default
        elif len(values) == 1:
            return values[0]
        else:
            raise ValueError(
                'More than one value present for %r' % (type_uri,))

    def get(self, type_uri):
        """Get the list of values for this attribute in the
        fetch_response.

        @param type_uri: The URI of the attribute

        @returns: The list of values for this attribute in the
            response. May be an empty list.
        @rtype: [unicode]

        @raises KeyError: If the attribute was not sent in the response
        """
        return self.data[type_uri]

    def count(self, type_uri):
        """Get the number of responses for a particular attribute in
        this fetch_response message.

        @param type_uri: The URI of the attribute

        @returns: The number of values sent for this attribute

        @raises KeyError: If the attribute was not sent in the
            response. KeyError will not be raised if the number of
            values was zero.
        """
        return len(self.get(type_uri))