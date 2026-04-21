import requests
import json
from sign_sdk import sign

key = "46a93978847c402ea03ac899d501ebed"
secret = "418c3dd21d0e44fb9157255675e11c7f"
url = "http://openapi.meitu.com/demo/authorization"
method = "POST"
headers = {
    "Content-Type": "application/json",
    sign.HeaderHost: "openapi.meitu.com",
    "X-Sdk-Content-Sha256": "UNSIGNED-PAYLOAD",  #在python-sdk-1.0.1及更高版本上，请求头添加了此参数时，请求的body不参与签名与验签
}
body = {"params":"aysdnfsdf"}

signer = sign.Signer(key, secret)

signed_request = signer.sign(url, method, headers, json.Dumps(body))
session = requests.Session()
response = session.send(signed_request)

print(response.status_code)
print(response.text)