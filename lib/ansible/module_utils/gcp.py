# This code is part of Ansible, but is an independent component.
# This particular file snippet, and this file snippet only, is BSD licensed.
# Modules you write using this snippet, which is embedded dynamically by Ansible
# still belong to the author of the module, and may assign their own license
# to the complete work.
#
# Copyright (c), Franck Cuny <franck.cuny@gmail.com>, 2014
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#    * Redistributions in binary form must reproduce the above copyright notice,
#      this list of conditions and the following disclaimer in the documentation
#      and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE
# USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

import json
import os
import traceback
from distutils.version import LooseVersion

# libcloud
try:
    import libcloud
    HAS_LIBCLOUD_BASE = True
except ImportError:
    HAS_LIBCLOUD_BASE = False

# google-auth
try:
    import google.auth
    from google.oauth2 import service_account
    HAS_GOOGLE_AUTH = True
except ImportError as e:
    HAS_GOOGLE_AUTH = False

# google-python-api
try:
    import google_auth_httplib2
    from httplib2 import Http
    from googleapiclient.http import set_user_agent
    HAS_GOOGLE_API_LIB = True
except ImportError:
    HAS_GOOGLE_API_LIB = False


# Ansible Display object for warnings
try:
    from __main__ import display
except ImportError:
    from ansible.utils.display import Display
    display = Display()

def _get_gcp_ansible_credentials(module):
    """Helper to fetch creds from AnsibleModule object."""
    service_account_email = module.params.get('service_account_email', None)
    # Note: pem_file is discouraged and will be deprecated
    credentials_file = module.params.get('pem_file', None) or module.params.get(
        'credentials_file', None)
    project_id = module.params.get('project_id', None)

    return (service_account_email, credentials_file, project_id)

def _get_gcp_environ_var(var_name, default_value):
    """Wrapper around os.environ.get call."""
    return os.environ.get(
        var_name, default_value)

def _get_gcp_environment_credentials(service_account_email, credentials_file, project_id):
    """Helper to look in environment variables for credentials."""
    # If any of the values are not given as parameters, check the appropriate
    # environment variables.
    if not service_account_email:
        service_account_email = _get_gcp_environ_var('GCE_EMAIL', None)
    if not credentials_file:
        credentials_file = _get_gcp_environ_var(
            'GCE_CREDENTIALS_FILE_PATH', None) or _get_gcp_environ_var(
                'GOOGLE_APPLICATION_CREDENTIALS', None) or _get_gcp_environ_var(
                    'GCE_PEM_FILE_PATH', None)
    if not project_id:
        project_id = _get_gcp_environ_var('GCE_PROJECT', None) or _get_gcp_environ_var(
            'GOOGLE_CLOUD_PROJECT', None)
    return (service_account_email, credentials_file, project_id)

def _get_gcp_libcloud_credentials(service_account_email=None, credentials_file=None, project_id=None):
    """
    Helper to look for libcloud secrets.py file.

    Note: This has an 'additive' effect right now, filling in
    vars not specified elsewhere, in order to keep legacy functionality.
    This method of specifying credentials will be deprecated, otherwise
    we'd look to make it more restrictive with an all-vars-or-nothing approach.

    :param service_account: GCP service account email used to make requests
    :type service_account: ``str`` or None

    :param credentials_file: Path on disk to credentials file
    :type credentials_file: ``str`` or None

    :param project_id: GCP project ID.
    :type project_id: ``str`` or None

    :return: tuple of (service_account, credentials_file, project_id)
    :rtype: ``tuple`` of ``str``
    """
    if service_account_email is None or credentials_file is None:
        try:
            import secrets
            display.deprecated(msg=("secrets file found at '%s'.  This method of specifying "
                                    "credentials is deprecated.  Please use env vars or "
                                    "Ansible YAML files instead" % (secrets.__file__)), version=2.5)
        except ImportError:
            secrets = None
        if hasattr(secrets, 'GCE_PARAMS'):
            if not service_account_email:
                service_account_email = secrets.GCE_PARAMS[0]
            if not credentials_file:
                credentials_file = secrets.GCE_PARAMS[1]
        keyword_params = getattr(secrets, 'GCE_KEYWORD_PARAMS', {})
        if not project_id:
            project_id = keyword_params.get('project', None)
    return (service_account_email, credentials_file, project_id)

def _get_gcp_credentials(module, require_valid_json=True, check_libcloud=False):
    """
    Obtain GCP credentials by trying various methods.

    There are 3 ways to specify GCP credentials:
    1. Specify via Ansible module parameters (recommended).
    2. Specify via environment variables.  Two sets of env vars are available:
       a) GOOGLE_CLOUD_PROJECT, GOOGLE_CREDENTIALS_APPLICATION (preferred)
       b) GCE_PROJECT, GCE_CREDENTIAL_FILE_PATH, GCE_EMAIL (legacy, not recommended; req'd if
          using p12 key)
    3. Specify via libcloud secrets.py file (deprecated).

    There are 3 helper functions to assist in the above.

    Regardless of method, the user also has the option of specifying a JSON
    file or a p12 file as the credentials file.  JSON is strongly recommended and
    p12 will be removed in the future.

    Additionally, flags may be set to require valid json and check the libcloud
    version.

    AnsibleModule.fail_json is called only if the project_id cannot be found.

    :param module: initialized Ansible module object
    :type module: `class AnsibleModule`

    :param require_valid_json: If true, require credentials to be valid JSON.  Default is True.
    :type require_valid_json: ``bool``

    :params check_libcloud: If true, check the libcloud version available to see if
                            JSON creds are supported.
    :type check_libcloud: ``bool``

    :return:  {'service_account_email': service_account_email,
               'credentials_file': credentials_file,
                'project_id': project_id}
    :rtype: ``dict``
    """
    (service_account_email,
     credentials_file,
     project_id) = _get_gcp_ansible_credentials(module)

    # If any of the values are not given as parameters, check the appropriate
    # environment variables.
    (service_account_email,
     credentials_file,
     project_id) = _get_gcp_environment_credentials(service_account_email,
                                                    credentials_file, project_id)

    # If we still don't have one or more of our credentials, attempt to
    # get the remaining values from the libcloud secrets file.
    (service_account_email,
     credentials_file,
     project_id) = _get_gcp_libcloud_credentials(service_account_email,
                                                 credentials_file, project_id)

    if credentials_file is None or project_id is None or service_account_email is None:
        if check_libcloud is True:
            if project_id is None:
                # TODO(supertom): this message is legacy and integration tests depend on it.
                module.fail_json(msg='Missing GCE connection parameters in libcloud '
                                 'secrets file.')
        else:
            if project_id is None:
                module.fail_json(msg=('GCP connection error: unable to determine project (%s) or '
                'credentials file (%s)' % (project_id, credentials_file)))
        # Set these fields to empty strings if they are None
        # consumers of this will make the distinction between an empty string
        # and None.
        if credentials_file is None:
            credentials_file = ''
        if service_account_email is None:
            service_account_email = ''

    # ensure the credentials file is found and is in the proper format.
    if credentials_file:
        _validate_credentials_file(module, credentials_file,
                                   require_valid_json=require_valid_json,
                                   check_libcloud=check_libcloud)

    return {'service_account_email': service_account_email,
            'credentials_file': credentials_file,
            'project_id': project_id}

def _validate_credentials_file(module, credentials_file, require_valid_json=True, check_libcloud=False):
    """
    Check for valid credentials file.

    Optionally check for JSON format and if libcloud supports JSON.

    :param module: initialized Ansible module object
    :type module: `class AnsibleModule`

    :param credentials_file: path to file on disk
    :type credentials_file: ``str``.  Complete path to file on disk.

    :param require_valid_json: If true, require credentials to be valid JSON.  Default is True.
    :type require_valid_json: ``bool``

    :params check_libcloud: If true, check the libcloud version available to see if
                            JSON creds are supported.
    :type check_libcloud: ``bool``

    :returns: True
    :rtype: ``bool``
    """
    try:
        # Try to read credentials as JSON
        with open(credentials_file) as credentials:
            json.loads(credentials.read())
            # If the credentials are proper JSON and we do not have the minimum
            # required libcloud version, bail out and return a descriptive error
            if check_libcloud and LooseVersion(libcloud.__version__) < '0.17.0':
                module.fail_json(msg='Using JSON credentials but libcloud minimum version not met. '
                                     'Upgrade to libcloud>=0.17.0.')
            return True
    except IOError as e:
        module.fail_json(msg='GCP Credentials File %s not found.' % credentials_file, changed=False)
        return False
    except ValueError as e:
        if require_valid_json:
            module.fail_json(msg='GCP Credentials File %s invalid.  Must be valid JSON.' % credentials_file, changed=False)
        else:
            display.deprecated(msg=("Non-JSON credentials file provided. This format is deprecated. "
                                    " Please generate a new JSON key from the Google Cloud console"),
                               version=2.5)
            return True


def gcp_connect(module, provider, get_driver, user_agent_product, user_agent_version):
    """Return a Google libcloud driver connection."""
    if not HAS_LIBCLOUD_BASE:
        module.fail_json(msg='libcloud must be installed to use this module')

    creds = _get_gcp_credentials(module,
                                 require_valid_json=False,
                                 check_libcloud=True)
    try:
        gcp = get_driver(provider)(creds['service_account_email'], creds['credentials_file'],
                datacenter=module.params.get('zone', None),
                                   project=creds['project_id'])
        gcp.connection.user_agent_append("%s/%s" % (
            user_agent_product, user_agent_version))
    except (RuntimeError, ValueError) as e:
        module.fail_json(msg=str(e), changed=False)
    except Exception as e:
        module.fail_json(msg=unexpected_error_msg(e), changed=False)

    return gcp


def get_google_cloud_credentials(module, scopes=[]):
    """
    Get credentials object for use with Google Cloud client.

    Attempts to obtain credentials by calling _get_gcp_credentials. If those are
    not present will attempt to connect via Application Default Credentials.

    To connect via libcloud, don't use this function, use gcp_connect instead.  For
    Google Python API Client, see get_google_api_auth for how to connect.

    For more information on Google's client library options for Python, see:
    U(https://cloud.google.com/apis/docs/client-libraries-explained#google_api_client_libraries)

    Google Cloud example:
      creds, params = get_google_cloud_credentials(module, scopes, user_agent_product, user_agent_version)
      pubsub_client = pubsub.Client(project=params['project_id'], credentials=creds)
      pubsub_client.user_agent = 'ansible-pubsub-0.1'
      ...

    :param module: initialized Ansible module object
    :type module: `class AnsibleModule`

    :param scopes: list of scopes
    :type module: ``list`` of URIs

    :returns: A tuple containing (google authorized) credentials object and
              params dict {'service_account_email': '...', 'credentials_file': '...', 'project_id': ...}
    :rtype: ``tuple``
    """
    if not HAS_GOOGLE_AUTH:
        module.fail_json(msg='Please install google-auth.')

    conn_params = _get_gcp_credentials(module,
                                 require_valid_json=True,
                                 check_libcloud=False)
    try:
        if conn_params['credentials_file']:
            credentials = service_account.Credentials.from_service_account_file(
                conn_params['credentials_file'])
            if scopes:
                credentials = credentials.with_scopes(scopes)
        else:
            (credentials, project_id) = google.auth.default(
                scopes=scopes)
            if project_id is not None:
                conn_params['project_id'] = project_id

        return (credentials, conn_params)
    except Exception as e:
        module.fail_json(msg=unexpected_error_msg(e), changed=False)
        return (None, None)

def get_google_api_auth(module, scopes=[], user_agent_product='ansible-python-api', user_agent_version='NA'):
    """
    Authentication for use with google-python-api-client.

    Function calls get_google_cloud_credentials, which attempts to assemble the credentials
    from various locations.  Next it attempts to authenticate with Google.

    This function returns an httplib2 (compatible) object that can be provided to the Google Python API client.

    For libcloud, don't use this function, use gcp_connect instead.  For Google Cloud, See
    get_google_cloud_credentials for how to connect.

    For more information on Google's client library options for Python, see:
    U(https://cloud.google.com/apis/docs/client-libraries-explained#google_api_client_libraries)

    Google API example:
      http_auth, conn_params = get_google_api_auth(module, scopes, user_agent_product, user_agent_version)
      service = build('myservice', 'v1', http=http_auth)
      ...

    :param module: initialized Ansible module object
    :type module: `class AnsibleModule`

    :param scopes: list of scopes
    :type scopes: ``list`` of URIs

    :param user_agent_product: User agent product.  eg: 'ansible-python-api'
    :type user_agent_product: ``str``

    :param user_agent_version: Version string to append to product.  eg: 'NA' or '0.1'
    :type user_agent_version: ``str``

    :returns: A tuple containing (google authorized) httplib2 request object and a
              params dict {'service_account_email': '...', 'credentials_file': '...', 'project_id': ...}
    :rtype: ``tuple``
    """
    if not HAS_GOOGLE_API_LIB:
        module.fail_json(msg="Please install google-api-python-client library")
    # TODO(supertom): verify scopes
    if not scopes:
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
    try:
        (credentials, conn_params) = get_google_cloud_credentials(module, scopes)
        http = set_user_agent(Http(), '%s-%s' % (user_agent_product, user_agent_version))
        http_auth = google_auth_httplib2.AuthorizedHttp(credentials, http=http)

        return (http_auth, conn_params)
    except Exception as e:
        module.fail_json(msg=unexpected_error_msg(e), changed=False)
        return (None, None)

def check_min_pkg_version(pkg_name, minimum_version):
    """Minimum required version is >= installed version."""
    from pkg_resources import get_distribution
    try:
        installed_version = get_distribution(pkg_name).version
        return LooseVersion(installed_version) >= minimum_version
    except Exception as e:
        return False

def unexpected_error_msg(error):
    """Create an error string based on passed in error."""
    return 'Unexpected response: (%s). Detail: %s' % (str(error), traceback.format_exc())

def get_valid_location(module, driver, location, location_type='zone'):
    if location_type == 'zone':
        l = driver.ex_get_zone(location)
    else:
        l = driver.ex_get_region(location)
    if l is None:
        link = 'https://cloud.google.com/compute/docs/regions-zones/regions-zones#available'
        module.fail_json(msg=('%s %s is invalid. Please see the list of '
                              'available %s at %s' % (
                                  location_type, location, location_type, link)),
                         changed=False)
    return l

def check_params(params, field_list):
    """
    Helper to validate params.

    Use this in function definitions if they require specific fields
    to be present.

    :param params: structure that contains the fields
    :type params: ``dict``

    :param field_list: list of dict representing the fields
                       [{'name': str, 'required': True/False', 'type': cls}]
    :type field_list: ``list`` of ``dict``

    :return True or raises ValueError
    :rtype: ``bool`` or `class:ValueError`
    """
    for d in field_list:
        if not d['name'] in params:
            if 'required' in d and d['required'] is True:
                raise ValueError(("%s is required and must be of type: %s" %
                        (d['name'], str(d['type']))))
        else:
            if not isinstance(params[d['name']], d['type']):
                raise ValueError(("%s must be of type: %s" % (
                    d['name'], str(d['type']))))
            if 'values' in d:
                if params[d['name']] not in d['values']:
                    raise ValueError(("%s must be one of: %s" % (
                        d['name'], ','.join(d['values']))))
            if isinstance(params[d['name']], int):
                if 'min' in d:
                    if params[d['name']] < d['min']:
                        raise ValueError(("%s must be greater than or equal to: %s" % (
                            d['name'], d['min'])))
                if 'max' in d:
                    if params[d['name']] > d['max']:
                        raise ValueError("%s must be less than or equal to: %s" % (
                            d['name'], d['max']))
    return True
