#    This file is part of rhizi, a collaborative knowledge graph editor.
#    Copyright (C) 2014-2015  Rhizi
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published
#    by the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""
 Utility code in speaking the neo4j REST api
"""

import json
import six
import string
import uuid

from six.moves.urllib import request
import six.moves.urllib_error as urllib_error
from six import iteritems

from .neo4j_cypher_parser import tok__quote__backquote, tok__quote__singlequote
from . import neo4j_schema
from .util import debug_log_duration


RESERVED_LABEL__EMPTY_STRING = '__EMPTY_STRING__'

class Neo4JException(Exception):
    def __init__(self, error_set):
        self.error_set = error_set

    def __str__(self):
        return 'neo4j error set: ' + str(self.error_set)

class Cypher_String_Formatter(string.Formatter):
    """
    Despite parameter support in Cypher, we sometimes do engage in query string building
    - as both Cypher & Python use brackets to wrap parameters, escaping them in Python makes
    queries less readable. This customized formatter will simply ignore unavailable keyworded
    formatting arguments, allowing the use of non-escaped parameter designation, eg:
    q = cfmt("match (a:{type} {cypher_param})", type='Book')
    """

    def get_field(self, field_name, args, kwargs):
        # ignore key not found, return bracket wrapped key
        try:
            val = super(Cypher_String_Formatter, self).get_field(field_name, args, kwargs)
        except (KeyError, AttributeError):
            val = "{" + field_name + "}", field_name
        return val

def __type_check_link_or_node_map(x_map):
    for k, v in iteritems(x_map):  # do some type sanity checking
        assert isinstance(k, six.string_types)
        assert isinstance(v, list)

def __type_check_filter_attr_map(filter_attr_map):
    """
    # type sanity check an attribute filter map
    """
    assert isinstance(filter_attr_map, dict)
    for k, v in filter_attr_map.items():
        assert isinstance(k, six.string_types)
        assert isinstance(v, list)

def cfmt(fmt_str, *args, **kwargs):
    """
    @deprecated
    """
    return Cypher_String_Formatter().format(fmt_str, *args, **kwargs)

def rzdoc__ns_label(rzdoc):
    """
    [!] must be quoted when used in queries
    """
    return neo4j_schema.META_LABEL__RZDOC_NS_PREFIX + rzdoc.id

def rzdoc__meta_ns_label(rzdoc):
    """
    [!] must be quoted when used in queries
    """
    return neo4j_schema.META_LABEL__RZDOC_NS_META_PREFIX + rzdoc.id

def db_query_set_to_REST_form(db_query_set):
    """
    Transform DB_Query set to Neo4J's REST API request format

    ref: http://neo4j.com/docs/stable/rest-api.html
    """

    assert isinstance(db_query_set, list)

    def _adapt_single_query_to_REST_form(query, parameters={}):
        """
        turn cypher query to neo4j json API format
        """
        assert isinstance(query, six.string_types)

        if isinstance(parameters, list):
            for v in parameters:
                assert isinstance(v, dict)
        else:
            assert isinstance(parameters, dict)

        return {'statement' : query,
                'parameters': parameters}

    rest_query_set = []
    for db_query in db_query_set:
        rest_query = _adapt_single_query_to_REST_form(db_query.str__cypher_query(),
                                                              db_query.param_set)
        rest_query_set.append(rest_query)

    return {'statements': rest_query_set}

def gen_clause_attr_filter_from_filter_attr_map(filter_attr_map, node_label="n"):
    if not filter_attr_map:
        return "{}"

    __type_check_filter_attr_map(filter_attr_map)

    filter_arr = []
    for attr_name in filter_attr_map.keys():
        # create a cypher query parameter place holder for each attr set
        # eg. n.foo in {foo}, where foo is passed as a query parameter
        f_attr = cfmt("{attr_name}: {{{attr}}}", attr_name=attr_name)
        filter_arr.append(f_attr)

    filter_str = "{{{0}}}".format(', '.join(filter_arr))
    return filter_str

def gen_clause_where_from_filter_attr_map(filter_attr_map, node_label="n"):
    """
    convert a filter attribute map to a parameterized Cypher where clause, eg.
    in: { 'att_foo': [ 'a', 'b' ], 'att_goo': [1, 2] }
    out: {att_foo: {att_foo}, att_goo: {att_goo}, ...}

    this function will essentially ignore all but the first value in the value list

    @param filter_attr_map: may be None or empty
    """
    if not filter_attr_map:
        return ""

    __type_check_filter_attr_map(filter_attr_map)

    filter_arr = []
    for attr in filter_attr_map.keys():
        # create a cypher query parameter place holder for each attr set
        # eg. n.foo in {foo}, where foo is passed as a query parameter
        f_attr = cfmt("{node_label}.{attr} in {{{attr}}}", node_label=node_label, attr=attr)
        filter_arr.append(f_attr)
    filter_str = "where {0}".format(' and '.join(filter_arr))
    return filter_str

def gen_query_create_from_node_map(node_map, input_to_DB_property_map=lambda _: _):
    """
    generate a set of node create queries

    @param node_map: is a node-type to node map
    @input_to_DB_property_map: optional function which takes a map of input
    properties and returns a map of DB properties - use to map input schemas to DB schemas

    @return: a (query, query_parameteres) set of create queries
    """
    __type_check_link_or_node_map(node_map)

    # merge does not support maps; we need merge to avoid multiple queries,
    # plus we have attr_diff for setting properties, so the client can do this
    # using two queries anyway (albiet two CSN round trips, instead of two SN)
    keys = set(sum([sum([list(x.keys()) for x in xs], []) for xs in node_map.values()], []))
    assert {'name', 'id'} >= keys

    node_label = neo4j_schema.META_LABEL__RZDOC_NODE

    ret = []
    for n_label, n_set in node_map.items():

        validate_label(n_label)

        q_arr = ['unwind {node_attrs} as node_attr',
                 'with node_attr.id as node_attr_id, node_attr.name as node_attr_name',
                 'merge (n:%s {name: node_attr_name})' % node_label,
                 'on create set n.id = node_attr_id',
                 'on create set n:%s' % quote__backtick(n_label),
                 'with n, node_attr_id',
                 'order by n.id',
                 'return {id: n.id, asked_id: node_attr_id, __label_set: labels(n)}'
                 ]

        q_params_set = []
        for n_prop_set in n_set:

            assert 'id' in n_prop_set, 'node create query: node id attribute not set'
            assert '__label_set' not in n_prop_set, 'node create query: out-of-place \'__label_set\' attribute in attribute set'

            q_params = input_to_DB_property_map(n_prop_set)
            q_params_set.append(q_params)

        q_tuple = (q_arr, {'node_attrs': q_params_set})
        ret.append(q_tuple)

    return ret

def gen_query_create_from_link_map(link_map, input_to_DB_property_map=lambda _: _):
    """
    generate a set of link create queries

    @param link_map: is a link-type to link-pointer map - see model.link
    """
    __type_check_link_or_node_map(link_map)

    # merge requirement, see longer comment above
    keys = set(sum([sum([list(x.keys()) for x in xs], []) for xs in link_map.values()], []))
    assert {'__src_id', '__dst_id', '__type', 'id'} >= keys

    # __type is ignored in the map

    ret = []
    for l_type, l_set in link_map.items():

        if l_type == '':
            l_type = RESERVED_LABEL__EMPTY_STRING
        validate_label(l_type);

        node_label = neo4j_schema.META_LABEL__RZDOC_NODE
        q_arr = ['match (src:%s {id: {src_id}}), (dst:%s {id: {dst_id}})' % (node_label, node_label),
                 'merge (src)-[r:%(__type)s {id: {link_id}}]->(dst)' % {'__type': quote__backtick(l_type)},
                 'with r, src, dst',
                 'order by r.id',
                 'return {id: r.id, __src_id: src.id, __dst_id: dst.id, __type: type(r)}',
                 ]

        for link in l_set:
            assert '__src_id' in link
            assert '__dst_id' in link
            assert 'id' in link, 'link create query: link id attribute not set'

            # TODO: use object based link representation
            l_prop_set = link.copy()

            del l_prop_set['__dst_id']
            del l_prop_set['__src_id']

            src_id = link['__src_id']
            dst_id = link['__dst_id']
            q_params = {'src_id': src_id,
                        'dst_id': dst_id,
                        'link_id' : input_to_DB_property_map(l_prop_set)['id']}

            q_tuple = (q_arr, q_params)
            ret.append(q_tuple)

    return ret

def generate_random_id__uuid():
    """
    generate a random UUID based string ID
    """
    return str(uuid.uuid4())

def generate_random_rzdoc_id():
    # grab last element of uuid, eg:
    # 'f6c2cea6-f2fc-43a8-a753-d2c73155c886' -> d2c73155c886
    ret = generate_random_id__uuid().split('-')[-1]
    return ret

def meta_attr_list_to_meta_attr_map(e_set, meta_attr='__label_set'):
    """
    convert a list of maps each containing a meta_attr key into a
    meta_attr-mapped collection of lists with the meta_attr removed - eg:

        nodes:
        in: [{'id':0, '__label_set': ['T']}, {'id':1, '__label_set': ['T']}]
        out: { 'T': [{'id':0}, {'id':1}] }

        links:
        in: [{'id':0, '__type': ['T']}, {'id':1, '__type': ['T']}]
        out: { 'T': [{'id':0}, {'id':1}] }

    [!] as of 2015-01 multiple labels for relations are not supported,
        which is why meta_attr='__type' should be used when calling this
        function to map links
    """

    assert '__label_set' == meta_attr or '__type' == meta_attr, 'type meta-attribute != __label_set or __type'

    ret = {}
    for v in e_set:
        meta_attr_list = v.get(meta_attr)
        assert None != meta_attr_list, 'element missing type meta-attribute'
        assert list == type(meta_attr_list), 'element with non-list type meta-attribute set: ' + str(v)

        if '__label_set' == meta_attr:
            assert 1 == len(meta_attr_list), 'only single-label mapping currently supported for nodes'
        if '__type' == meta_attr:
            assert 1 == len(meta_attr_list), 'only single-type mapping currently supported by neo4j for links'

        v_type = v[meta_attr][0]
        if None == ret.get(v_type):  # initialize type list if necessary
            ret[v_type] = []

        v_no_meta = v.copy()
        del v_no_meta[meta_attr]

        ret[v_type].append(v_no_meta)

    return ret

def post_neo4j(url, data):
    """
    @return dict object from the neo4j json POST response
    """
    ret = post(url, data)
    ret_data = json.loads(ret.read().decode('utf-8'))

    # [!] do not raise exception if ret_data['errors'] is not empty -
    # this allows query-sets to partially succeed

    return ret_data

def post(url, data):
    assert(isinstance(data, dict))  # make sure we're not handed json strings

    post_data_json = json.dumps(data).encode('utf-8')

    req = request.Request(url)
    req.add_header('User-Agent', 'rhizi-server/0.1')
    req.add_header('Accept', 'application/json; charset=UTF-8')
    req.add_header('Content-Type', 'application/json')

    req.add_header('X-Stream', 'true')  # enable neo4j JSON streaming

    #
    # see issue #419
    #
    # Add neo4j HTTP Basic Auth header
    #
    # neo4j_user = current_app.rz_config.neo4j_user
    # neo4j_pw = current_app.rz_config.neo4j_pw
    # user_pw_base64 = base64.encodestring('%s:%s' % (neo4j_user, neo4j_pw))
    # req.add_header('Authorization', 'Basic ' + user_pw_base64)  # enable neo4j JSON streaming

    try:
        ret = request.urlopen(req, post_data_json)
    except urllib_error.HTTPError as e:
        raise Exception('post request failed: code: {0}, reason: {1}'.format(e.code, e.reason))

    return ret

def quote__backtick(label):
    """
    quote label (possibly containing spaces) with backticks
    """
    return tok__quote__backquote + label + tok__quote__backquote

def quote__singlequote(label):
    """
    quote label (possibly containing spaces) with single quotes
    """
    return tok__quote__singlequote + label + tok__quote__singlequote

def validate_label(label):
    assert len(label) > 0, 'malformed label: ' + label
