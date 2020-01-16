"""
Search objects on elasticsearch
"""
import json
import requests
import logging

from src.workspace_auth import ws_auth
from src.utils.config import init_config

_CONFIG = init_config()

logger = logging.getLogger('searchapi2')


def search_objects(params, headers):
    """
    Make a query on elasticsearch using the given index and options.

    See method_schemas.json for a definition of the params

    ES 5.5 search query documentation:
    https://www.elastic.co/guide/en/elasticsearch/reference/5.5/search-request-body.html
    """
    user_query = params.get('query')
    authorized_ws_ids = []  # type: list
    if not params.get('public_only') and headers.get('Authorization'):
        # Fetch the workspace IDs that the user can read
        # Used for simple access control
        authorized_ws_ids = ws_auth(headers['Authorization'])
    # Get the index name(s) to include and exclude (used in the URL below)
    index_name_str = _construct_index_name(params)
    # We insert the user's query as a "must" entry
    query = {'bool': {}}  # type: dict
    if user_query:
        query['bool']['must'] = user_query
    # Our access control query is then inserted under a "filter" depending on options:
    if params.get('public_only'):
        # Public workspaces only; most efficient
        query['bool']['filter'] = {'term': {'is_public': True}}
    elif params.get('private_only'):
        # Private workspaces only
        query['bool']['filter'] = [
            {'term': {'is_public': False}},
            {'terms': {'access_group': authorized_ws_ids}}
        ]
    else:
        # Find all documents, whether private or public
        query['bool']['filter'] = {
            'bool': {
                'should': [
                    {'term': {'is_public': True}},
                    {'terms': {'access_group': authorized_ws_ids}}
                ]
            }
        }
    # Make a query request to elasticsearch
    url = _CONFIG['elasticsearch_url'] + '/' + index_name_str + '/_search'
    logger.debug(f"QUERY: {query}")
    options = {
        'query': query,
        'size': 0 if params.get('count') else params.get('size', 10),
        'from': params.get('from', 0),
        'timeout': '3m'  # type: ignore
    }
    if not params.get('count') and params.get('size', 10) > 0:
        options['terminate_after'] = 10000  # type: ignore
    # User-supplied aggregations
    if params.get('aggs'):
        options['aggs'] = params['aggs']
    # User-supplied sorting rules
    if params.get('sort'):
        options['sort'] = params['sort']
    # User-supplied source filters
    if params.get('source'):
        options['_source'] = params.get('source')
    # Search results highlighting
    if params.get('highlight'):
        options['highlight'] = {'require_field_match': False, 'fields': params['highlight']}
    headers = {'Content-Type': 'application/json'}
    resp = requests.post(url, data=json.dumps(options), headers=headers)
    if not resp.ok:
        # Unexpected elasticsearch error
        raise RuntimeError(resp.text)
    return resp.json()


def _construct_index_name(params):
    """
    Given the search_objects params, construct the index name for use in the
    URL of the query.
    See the docs about how this works:
        https://www.elastic.co/guide/en/elasticsearch/reference/current/multi-index.html
    """
    prefix = _CONFIG['index_prefix']
    # index_name_str = prefix + "."
    index_name_str = prefix + ".default_search"
    if params.get('indexes'):
        index_names = [
            prefix + '.' + name.lower()
            for name in params['indexes']
        ]
        # Replace the index_name_str with all explicitly included index names
        index_name_str = ','.join(index_names)
    # Append any index name exclusions, if necessary
    if params.get('exclude_indexes'):
        exclusions = params['exclude_indexes']
        exclusions_str = ','.join('-' + prefix + '.' + name for name in exclusions)
        index_name_str += ',' + exclusions_str
    return index_name_str
