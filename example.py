#!/usr/bin/env python3
import os
import sys
import time
import logging
import ssl
import json
import base64
import xmlrpc.client as xmlrpc_client
import xmltodict  # pip install xmltodict

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

PACKAGE_VERSION = 0.1

try:
    LOGIN_ID  = os.environ['USER']
    PEM_PWORD = os.environ['PWORD']
    CERT_PATH = os.environ['CERT']
except KeyError:
    logging.error("Missing CloudLab credential environment variables (USER, PWORD, CERT)")
    sys.exit(1)

XMLRPC_SERVER = "boss.emulab.net"
XMLRPC_PORT   = 3069
SERVER_PATH   = "/usr/testbed"
URI = f"https://{XMLRPC_SERVER}:{XMLRPC_PORT}{SERVER_PATH}"

RESPONSE_SUCCESS = 0

def do_method(method, params):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.load_cert_chain(CERT_PATH, password=PEM_PWORD)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    server = xmlrpc_client.ServerProxy(URI, context=ctx)
    meth = getattr(server, "portal." + method)
    meth_args = [PACKAGE_VERSION, params]
    try:
        response = meth(*meth_args)
    except xmlrpc_client.Fault as e:
        logging.error("XMLRPC Fault: %s", e.faultString)
        return -1, None
    return response.get("code", -1), response

def start_experiment(experiment_name, project_name, profile_name, ssh_pub_key_b64):
    params = {
        "name": experiment_name,
        "proj": project_name,
        "profile": f"{project_name},{profile_name}",
        "parambindings": json.dumps([
            {
                "name": "CLOUDLAB_SSH_PUB_KEY_B64",
                "value": ssh_pub_key_b64
            }
        ])
    }
    logging.info("Starting experiment with parameters: %s", params)
    return do_method("startExperiment", params)

def get_experiment_status(project_name, experiment_name):
    params = {"experiment": f"{project_name},{experiment_name}"}
    return do_method("experimentStatus", params)

def get_experiment_manifests(project_name, experiment_name):
    params = {"experiment": f"{project_name},{experiment_name}"}
    return do_method("experimentManifests", params)

def wait_for_experiment_ready(experiment_name, project_name, max_retries=30, delay=20):
    logging.info("Waiting for experiment '%s' to become ready...", experiment_name)
    for _ in range(max_retries):
        time.sleep(delay)
        rval, response = get_experiment_status(project_name, experiment_name)
        status_output = response.get("output", "").lower() if response else ""
        logging.info("Experiment status: %s", status_output.strip())
        if "ready" in status_output:
            return True
    logging.error("Experiment '%s' did not become ready in time.", experiment_name)
    return False

def extract_node_ip(manifest_output):
    try:
        json_manifest = json.loads(manifest_output)
        xml_string = next(iter(json_manifest.values()))
        manifest_dict = xmltodict.parse(xml_string)
        node = manifest_dict.get("rspec", {}).get("node")
        if isinstance(node, list):
            node = node[0]
        host = node.get("host")
        return host.get("@ipv4") if host else None
    except Exception as e:
        logging.error("XML parsing failed: %s", e)
        return None

def main():
    project_name = os.environ.get("CLOUDLAB_PROJECT_NAME", "YourProject")
    profile_name = os.environ.get("CLOUDLAB_PROFILE_NAME", "default-profile")
    experiment_name = os.environ.get("EXPERIMENT_NAME", f"{profile_name}-experiment")

    with open("public_key.txt") as f:
        ssh_pub_key = f.read().strip()
        ssh_pub_key_b64 = base64.b64encode(ssh_pub_key.encode()).decode()

    logging.info("Using experiment name: %s", experiment_name)

    rval, response = get_experiment_status(project_name, experiment_name)
    if rval == RESPONSE_SUCCESS:
        status_output = response.get("output", "").lower()
        if any(keyword in status_output for keyword in ["ready", "provisioning", "provisioned"]):
            logging.info("Experiment already running: %s", status_output.strip())
        else:
            rval, response = start_experiment(experiment_name, project_name, profile_name, ssh_pub_key_b64)
            if rval != RESPONSE_SUCCESS or not wait_for_experiment_ready(experiment_name, project_name):
                sys.exit(1)
    else:
        rval, response = start_experiment(experiment_name, project_name, profile_name, ssh_pub_key_b64)
        if rval != RESPONSE_SUCCESS or not wait_for_experiment_ready(experiment_name, project_name):
            sys.exit(1)

    rval, response = get_experiment_manifests(project_name, experiment_name)
    manifest_output = response.get("output", "")
    logging.info("Experiment manifest output:\n%s", manifest_output)
    node_ip = extract_node_ip(manifest_output)
    if node_ip:
        logging.info("Found deploy node IP: %s", node_ip)
        with open("node_ip.txt", "w") as f:
            f.write(node_ip)
    else:
        logging.error("Could not extract node IP from experiment manifests")
        sys.exit(1)

if __name__ == "__main__":
    main()
