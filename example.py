#!/usr/bin/env python3
import os
import sys
import time
import logging
import subprocess
import ssl
import json
import xmlrpc.client as xmlrpc_client
import xmltodict  # Requires: pip install xmltodict

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

def start_experiment(experiment_name, project_name, profile_name):
    params = {
        "name": experiment_name,
        "proj": project_name,
        "profile": f"{project_name},{profile_name}"
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
    # Try to load as JSON. If successful, extract the XML string.
    xml_str = None
    try:
        manifest_json = json.loads(manifest_output)
        for key, value in manifest_json.items():
            if isinstance(value, str) and value.strip().startswith("<rspec"):
                xml_str = value
                break
        if not xml_str:
            logging.error("No XML manifest found in JSON output.")
            return None
    except Exception:
        # Assume output is raw XML if JSON parsing fails.
        xml_str = manifest_output

    try:
        manifest_dict = xmltodict.parse(xml_str)
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
    logging.info("Using experiment name: %s", experiment_name)
    
    logging.info("Checking status for experiment '%s'...", experiment_name)
    rval, response = get_experiment_status(project_name, experiment_name)
    if rval == RESPONSE_SUCCESS:
        status_output = response.get("output", "").lower()
        if any(keyword in status_output for keyword in ["ready", "provisioning", "provisioned"]):
            logging.info("Experiment '%s' is already running: %s", experiment_name, status_output.strip())
        else:
            logging.info("Experiment '%s' exists but is not running: %s", experiment_name, status_output.strip())
            rval, response = start_experiment(experiment_name, project_name, profile_name)
            if rval != RESPONSE_SUCCESS:
                logging.error("Failed to start experiment: %s", response)
                sys.exit(1)
            if not wait_for_experiment_ready(experiment_name, project_name):
                sys.exit(1)
    else:
        logging.info("No existing experiment found with name '%s'. Starting a new experiment...", experiment_name)
        rval, response = start_experiment(experiment_name, project_name, profile_name)
        if rval != RESPONSE_SUCCESS:
            logging.error("Failed to start experiment: %s", response)
            sys.exit(1)
        if not wait_for_experiment_ready(experiment_name, project_name):
            sys.exit(1)
    
    rval, response = get_experiment_manifests(project_name, experiment_name)
    manifest_output = response.get("output", "")
    logging.info("Experiment manifest output:\n%s", manifest_output)
    
    node_ip = extract_node_ip(manifest_output)
    if node_ip:
        logging.info("Found deploy node IP: %s", node_ip)
    else:
        logging.error("Could not extract node IP from experiment manifests")
        sys.exit(1)
    
    ssh_cmd = [
        "ssh",
        "--vvv"
        "-o", "StrictHostKeyChecking=no",
        "-i", CERT_PATH,
        f"{LOGIN_ID}@{node_ip}",
        "hostname"
    ]
    logging.info("Executing SSH command: %s", " ".join(ssh_cmd))
    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
        hostname = result.stdout.strip()
        logging.info("Remote node hostname: %s", hostname)
    except subprocess.CalledProcessError as e:
        logging.error("SSH command failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
