import os, json, tempfile, filecmp
from nose.tools import assert_raises, assert_equal, assert_in
from mock import MagicMock, patch
import unit
from synapseclient.exceptions import *
from synapseclient import Evaluation, File, client, Synapse

def setup(module):
    print('\n')
    print('~' * 60)
    print(os.path.basename(__file__))
    print('~' * 60)
    module.syn = unit.syn


@patch('synapseclient.Synapse._loggedIn')
@patch('synapseclient.Synapse.restDELETE')
@patch('synapseclient.Synapse._readSessionCache')
@patch('synapseclient.Synapse._writeSessionCache')
def test_logout(*mocks):
    mocks = [item for item in mocks]
    logged_in_mock     = mocks.pop()
    delete_mock        = mocks.pop()
    read_session_mock  = mocks.pop()
    write_session_mock = mocks.pop()
    
    # -- Logging out while not logged in shouldn't do anything --
    logged_in_mock.return_value = False
    syn.username = None
    syn.logout()
    syn.logout()
    
    assert not delete_mock.called
    assert not write_session_mock.called


@patch('synapseclient.Synapse._getFileHandleDownload')
@patch('synapseclient.Synapse._downloadFileHandle')
def test_getWithEntityBundle(download_file_mock, get_file_URL_and_metadata_mock):
    ## Note: one thing that remains unexplained is why the previous version of
    ## this test worked if you had a .cacheMap file of the form:
    ## {"/Users/chris/.synapseCache/663/-1337/anonymous": "2014-09-15T22:54:57.000Z",
    ##  "/var/folders/ym/p7cr7rrx4z7fw36sxv04pqh00000gq/T/tmpJ4nz8U": "2014-09-15T23:27:25.000Z"}
    ## ...but failed if you didn't.

    bundle = {
        'entity': {
            'id': 'syn10101',
            'name': 'anonymous',
            'dataFileHandleId': '-1337',
            'concreteType': 'org.sagebionetworks.repo.model.FileEntity',
            'parentId': 'syn12345'},
        'fileHandles': [{
            'concreteType': 'org.sagebionetworks.repo.model.file.S3FileHandle',
            'fileName': 'anonymous',
            'contentType': 'application/flapdoodle',
            'contentMd5': '1698d26000d60816caab15169efcd23a',
            'id': '-1337'}],
        'annotations': {}}

    fileHandle = bundle['fileHandles'][0]['id']
    cacheDir = syn.cache.get_cache_dir(fileHandle)
    print("cacheDir=", cacheDir)

    # Make sure the .cacheMap file does not already exist
    cacheMap = os.path.join(cacheDir, '.cacheMap')
    if os.path.exists(cacheMap):
        print("removing cacheMap file: ", cacheMap)
        os.remove(cacheMap)

    def _downloadFileHandle(url, path, fileHandle, retries=5):
        print("mock downloading file to:", path)
        ## touch file at path
        with open(path, 'a'):
            os.utime(path, None)
        dest_dir, filename = os.path.split(path)
        return path

    def _getFileHandleDownload(fileHandleId,  objectId, objectType='FileHandle'):
        print("getting metadata for:", fileHandleId)
        return {'fileHandle':bundle['fileHandles'][0], 'fileHandleId':fileHandleId, 'preSignedURL':'http://example.com'}

    download_file_mock.side_effect = _downloadFileHandle
    get_file_URL_and_metadata_mock.side_effect = _getFileHandleDownload

    # 1. ----------------------------------------------------------------------
    # download file to an alternate location

    temp_dir1 = tempfile.mkdtemp()
    print("temp_dir1=", temp_dir1)

    e = syn._getWithEntityBundle(entityBundle=bundle,
                                 downloadLocation=temp_dir1,
                                 ifcollision="overwrite.local")
    print(e)

    assert e.name == bundle["entity"]["name"]
    assert e.parentId == bundle["entity"]["parentId"]
    assert os.path.dirname(e.path) == temp_dir1
    assert bundle["fileHandles"][0]["fileName"] == os.path.basename(e.path)
    assert e.path == os.path.join(temp_dir1, bundle["fileHandles"][0]["fileName"])

    # 2. ----------------------------------------------------------------------
    # get without specifying downloadLocation
    e = syn._getWithEntityBundle(entityBundle=bundle, ifcollision="overwrite.local")

    print(e)

    assert e.name == bundle["entity"]["name"]
    assert e.parentId == bundle["entity"]["parentId"]
    assert bundle["fileHandles"][0]["fileName"] in e.files

    # 3. ----------------------------------------------------------------------
    # download to another location
    temp_dir2 = tempfile.mkdtemp()
    assert temp_dir2 != temp_dir1
    e = syn._getWithEntityBundle(entityBundle=bundle,
                                 downloadLocation=temp_dir2,
                                 ifcollision="overwrite.local")
    print("temp_dir2=", temp_dir2)
    print(e)

    assert_in(bundle["fileHandles"][0]["fileName"], e.files)
    assert e.path is not None
    assert utils.equal_paths( os.path.dirname(e.path), temp_dir2 )

    # 4. ----------------------------------------------------------------------
    ## test preservation of local state
    url = 'http://foo.com/secretstuff.txt'
    e = File(name='anonymous', parentId="syn12345", synapseStore=False, externalURL=url)
    e.local_state({'zap':'pow'})
    e = syn._getWithEntityBundle(entityBundle=bundle, entity=e)
    assert e.local_state()['zap'] == 'pow'
    assert e.synapseStore == False
    assert e.externalURL == url

    ## TODO: add more test cases for flag combination of this method
    ## TODO: separate into another test?


@patch('synapseclient.Synapse.restPOST')
@patch('synapseclient.Synapse.getEvaluation')
def test_submit(*mocks):
    mocks = [item for item in mocks]
    POST_mock       = mocks.pop()
    getEvaluation_mock = mocks.pop()
    
    # -- Unmet access rights --
    getEvaluation_mock.return_value = Evaluation(**{u'contentSource': u'syn1001',
                                                    u'createdOn': u'2013-11-06T06:04:26.789Z',
                                                    u'etag': u'86485ea1-8c89-4f24-a0a4-2f63bc011091',
                                                    u'id': u'9090',
                                                    u'name': u'test evaluation',
                                                    u'ownerId': u'1560252',
                                                    u'status': u'OPEN',
                                                    u'submissionReceiptMessage': u'mmmm yummy!'})

    
    # -- Normal submission --
    # insert a shim that returns the dictionary it was passed after adding a bogus id
    def shim(*args):
        assert args[0] == '/evaluation/submission?etag=Fake eTag'
        submission = json.loads(args[1])
        submission['id'] = 1234
        return submission
    POST_mock.side_effect = shim
    
    submission = syn.submit('9090', {'versionNumber': 1337, 'id': "Whee...", 'etag': 'Fake eTag'}, name='George', submitterAlias='Team X')

    assert submission.id == 1234
    assert submission.evaluationId == '9090'
    assert submission.name == 'George'
    assert submission.submitterAlias == 'Team X'

    print(submission)


def test_send_message():
    with patch("synapseclient.multipart_upload._multipart_upload") as up_mock, patch("synapseclient.client.Synapse.restPOST") as post_mock:
            up_mock.return_value = {
                'startedOn': '2016-01-22T00:00:00.000Z',
                'state': 'COMPLETED',
                'uploadId': '1234',
                'updatedOn': '2016-01-22T00:00:00.000Z',
                'partsState': '11',
                'startedBy': '377358',
                'resultFileHandleId': '7365905' }
            syn.sendMessage(
                userIds=[1421212],
                messageSubject="Xanadu",
                messageBody=   ("In Xanadu did Kubla Khan\n"
                                "A stately pleasure-dome decree:\n"
                                "Where Alph, the sacred river, ran\n"
                                "Through caverns measureless to man\n"
                                "Down to a sunless sea.\n"))
            msg = json.loads(post_mock.call_args_list[0][1]['body'])
            assert msg["fileHandleId"] == "7365905", msg
            assert msg["recipients"] == [1421212], msg
            assert msg["subject"] == "Xanadu", msg

@patch("synapseclient.Synapse._getDefaultUploadDestination")
def test__uploadExternallyStoringProjects_external_user(mock_upload_destination):
    # setup
    expected_storage_location_id = "1234567"
    expected_local_state = {}
    expected_path = "~/fake/path/file.txt"
    mock_upload_destination.return_value = {'storageLocationId' : expected_storage_location_id,
                                            'concreteType' : client._EXTERNAL_S3_UPLOAD_DESTINATION_TYPE}

    test_file = File(expected_path, parent="syn12345")

    # method under test
    path, local_state,  storage_location_id = syn._Synapse__uploadExternallyStoringProjects(test_file, local_state={}) #dotn care about localstate for this test

    #test
    mock_upload_destination.assert_called_once_with(test_file)
    assert_equal(expected_path, path)
    assert_equal(expected_local_state, local_state)
    assert_equal(expected_storage_location_id, storage_location_id)