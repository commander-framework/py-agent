import json


def testUpdateRegKey(client, sample_RegistrationKey, sample_valid_Session, sample_User):
    # prepare mongomock with relevant sample documents
    user = sample_User
    user["sessions"].append(sample_valid_Session)
    user.save()
    regkey = sample_RegistrationKey
    regkey.save()
    # create a new registration key
    response = client.put("/admin/registration-key",
                          headers={"Content-Type": "application/json",
                                   "Auth-Token": sample_valid_Session["authToken"],
                                   "Username": sample_User["username"]},
                          data=json.dumps({}))
    assert response.status_code == 200
    assert "registration-key" in response.json


def testNewRegKey(client, sample_valid_Session, sample_User):
    # prepare mongomock with relevant sample documents
    user = sample_User
    user["sessions"].append(sample_valid_Session)
    user.save()
    # create a new registration key
    response = client.put("/admin/registration-key",
                          headers={"Content-Type": "application/json",
                                   "Auth-Token": sample_valid_Session["authToken"],
                                   "Username": sample_User["username"]},
                          data=json.dumps({}))
    assert response.status_code == 200
    assert "registration-key" in response.json


def testExpiredSessionNewRegKey(client, sample_expired_Session, sample_User):
    # prepare mongomock with relevant sample documents
    user = sample_User
    user["sessions"].append(sample_expired_Session)
    user.save()
    # make test session validation
    response = client.put("/admin/registration-key",
                          headers={"Content-Type": "application/json",
                                   "Auth-Token": sample_expired_Session["authToken"],
                                   "Username": sample_User["username"]},
                          data=json.dumps({}))
    assert response.status_code == 401
    assert response.json["error"] == "invalid auth token or token expired"


def testMissingFieldsNewRegKey(client, sample_valid_Session, sample_User):
    # prepare mongomock with relevant sample documents
    user = sample_User
    user["sessions"].append(sample_valid_Session)
    user.save()
    # make test session validation
    response = client.put("/admin/registration-key",
                          headers={"Content-Type": "application/json"},
                          data=json.dumps({}))
    assert response.status_code == 400
    assert response.json["error"] == "request is missing the following parameters: headers=['Auth-Token', 'Username']"