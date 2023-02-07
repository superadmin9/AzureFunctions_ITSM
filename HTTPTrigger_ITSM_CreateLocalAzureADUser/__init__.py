import json
import logging
import os
import adal
import azure.functions as func
import requests
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
import time

# Get client ID, secret, and tenant ID from environment variables
client_id = os.environ['client_id']
client_secret = os.environ['client_secret']
tenant_id = os.environ['tenant_id']

# Initialize the authentication context
context = adal.AuthenticationContext(f"https://login.microsoftonline.com/{tenant_id}")

def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    logging.info("Received request with body: %s", req.get_body())

    # Get input parameters from the HTTP request body
    req_body = req.get_json()
    logging.info('Req body is %s', req_body)
    old_email = req_body.get('old_email')
    logging.info('old email is %s', old_email)
    new_email = req_body.get('new_email')
    logging.info('new email is %s', new_email)
    client_application = req_body.get('client_application')
    full_name = req_body.get('full_name')
    logging.info('Full name is %s', full_name)
    name_parts = full_name.split()
    first_name = name_parts[0]
    last_name = name_parts[-1]
    logging.info('Full name is %s', full_name)
    logging.info('First name is %s', first_name)
    logging.info('Last name is %s', last_name)

    # Get an access token for the Microsoft Graph API
    token = context.acquire_token_with_client_credentials(
        "https://graph.microsoft.com",
        client_id,
        client_secret
    )
    headers = {
        "Authorization": f"Bearer {token['accessToken']}",
        "Content-Type": "application/json"
    }

    # Search for an existing user with the specified email address
    try:
        response = requests.get(f"https://graph.microsoft.com/v1.0/users?$filter=mail eq '{old_email}' or otherMails/any(x:x eq '{old_email}') or proxyAddresses/any(x:x eq '{old_email}')", headers=headers)
        try:
            user = response.json()["value"][0]
            logging.info('Found User %s',user)
            old_email_object_id = user['id']
            # Get the groups that the old_email user is a member of
            response = requests.get(f"https://graph.microsoft.com/v1.0/users/{old_email_object_id}/memberOf", headers=headers)
            try:
                groups = response.json()["value"]
                logging.info("Old Users Groups %s", groups)
            except KeyError:
                groups = []
                logging.info(f"User {old_email} not a member of any groups.")
            # If the user was found, delete the account
            if user:
                requests.delete(f"https://graph.microsoft.com/v1.0/users/{old_email_object_id}", headers=headers)
                logging.info(f'Deleted user with email "{old_email}".')
        except IndexError:
            logging.info(f"User {old_email} not found.")
    except:
        pass
    
    # 15 second pause
    time.sleep(15)
    

    # Create a new Local Azure AD User
    try:
        # Create a new Azure AD local user account
        upn = first_name + "." + last_name + "@wedc.onmicrosoft.com"
        mailnickname =  first_name + last_name       
        new_user_data = {
            "accountEnabled": True,
            "displayName": full_name,
            "mailNickname": mailnickname,
            "userPrincipalName": upn,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": "WelcomeToWEDC!"
            },
            "mail": new_email
        }
        logging.info("New Account Data %s", new_user_data)
        payload = '''{
            "accountEnabled": true,
            "displayName": "{}",
            "mailNickname": "{}",
            "userPrincipalName": "{}",
            "passwordProfile": {{
                "forceChangePasswordNextSignIn": true,
                "password": "{}"
            }},
            "email": "{}"
        }}'''.format(full_name, first_name + last_name, "{}@mydomain.onmicrosoft.com".format(first_name + "." + last_name), "WelcomeToWEDC!", new_email)
        logging.info("New Account Payload %s", payload)
        response = requests.post("https://graph.microsoft.com/v1.0/users", headers=headers, json=payload)
        logging.info("New Account Payload %s", payload)

        logging.info("New Account Headers %s", headers)
        logging.info("New Account Response %s", response)
        response.raise_for_status()

        new_user = response.json()
        new_user_id = new_user["id"]
    except Exception as e:
        return func.HttpResponse(f'Error Creating User: {str(e)}', status_code=500)

# Add the new_email user to each group
    for group in groups:
        requests.post(f"https://graph.microsoft.com/v1.0/groups/{group['id']}/members/$ref", json={"@odata.id": f"https://graph.microsoft.com/v1.0/users/{new_user_id}"}, headers=headers)
        logging.info(f'Added user with email "{new_email}" to group "{group["displayName"]}".')

    
    # Add the new user to the security group with object id 12345-45678-4564789
    group_id = os.environ['EXNonB2BAzGroupId']
    url = f"https://graph.microsoft.com/v1.0/groups/{group_id}/members/$ref"
    data = {"@odata.id": f"https://graph.microsoft.com/v1.0/users/{new_user_id}"}
    response = requests.post(url, headers=headers, json=data)

    if response.status_code != 204:
        logging.error("Failed to add user to group %s", response.text)
    else:
        logging.info("Successfully added user to group")

    



    # Return a success message
    return func.HttpResponse(f'Successfully created user with email "{new_email}" and added to groups associated with "{old_email}"', status_code=200)
