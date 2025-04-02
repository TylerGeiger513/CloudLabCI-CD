#!/usr/bin/env python3
import os
import sys
import time
import logging
import re
import subprocess
import ssl
import xmlrpc.client as xmlrpc_client

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

# Client package version for the API
PACKAGE_VERSION = 0.1

# Read CloudLab/Emulab credentials from environment variables.
try:
    LOGIN_ID  = os.environ['USER']
    PEM_PWORD = os.environ['PWORD']
    CERT_PATH = os.environ['CERT']
except KeyError:
    logging.error("Missing CloudLab credential environment variables (USER, PWORD, CERT)")
    sys.exit(1)

# XML-RPC server configuration for Emulab/CloudLab.
XMLRPC_SERVER = "boss.emulab.net"
XMLRPC_PORT   = 3069
SERVER_PATH   = "/usr/testbed"
URI           = "https://" + XMLRPC_SERVER + ":" + str(XMLRPC_PORT) + SERVER_PATH

RESPONSE_SUCCESS = 0

def do_method(method, params):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.load_cert_chain(CERT_PATH, password=PEM_PWORD)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    server = xmlrpc_client.ServerProxy(URI, context=ctx)
    meth = getattr(server, "portal." + method)
    # Use the PACKAGE_VERSION constant instead of hardcoding 1.0
    meth_args = [PACKAGE_VERSION, params]

    try:
        response = meth(*meth_args)
    except xmlrpc_client.Fault as e:
        logging.error("XMLRPC Fault: %s", e.faultString)
        return -1, None

    rval = response.get("code", -1)
    return rval, response

def start_experiment(experiment_name, project_name, profile_name):
    params = {
        "name": experiment_name,
        "proj": project_name,
        "profile": ','.join([project_name, profile_name])
    }
    logging.info("Starting experiment with parameters: %s", params)
    rval, response = do_method("startExperiment", params)
    return rval, response

def get_experiment_status(project_name, experiment_name):
    params = {
        "experiment": ','.join([project_name, experiment_name])
    }
    rval, response = do_method("experimentStatus", params)
    return rval, response

def get_experiment_manifests(project_name, experiment_name):
    params = {
        "experiment": ','.join([project_name, experiment_name])
    }
    rval, response = do_method("experimentManifests", params)
    return rval, response

def main():
    # Generate a unique experiment name using a timestamp.
    experiment_name = "exp-" + str(int(time.time()))
    project_name    = os.environ.get("CLOUDLAB_PROJECT_NAME", "YourProject")
    profile_name    = os.environ.get("CLOUDLAB_PROFILE_NAME", "default-profile")
    
    logging.info("Using experiment name: %s", experiment_name)
    
    # Start the experiment.
    rval, response = start_experiment(experiment_name, project_name, profile_name)
    if rval != RESPONSE_SUCCESS:
        logging.error("Failed to start experiment: %s", response)
        sys.exit(1)
    
    logging.info("Waiting for experiment '%s' to become ready...", experiment_name)
    for i in range(30):  # Poll for up to ~10 minutes (30 x 20s)
        time.sleep(20)
        rval, response = get_experiment_status(project_name, experiment_name)
        status_output = response.get("output", "").lower()
        logging.info("Experiment status: %s", status_output.strip())
        if "ready" in status_output:
            break
    else:
        logging.error("Experiment did not become ready in time")
        sys.exit(1)
    
    # Retrieve experiment manifests to extract the deploy node's IP.
    rval, response = get_experiment_manifests(project_name, experiment_name)
    manifest_output = response.get("output", "")
    
    # Simplistic regex to find an IPv4 address in the manifest.
    m = re.search(r'ipv4:\s*([\d\.]+)', manifest_output)
    if m:
        node_ip = m.group(1)
        logging.info("Found deploy node IP: %s", node_ip)
    else:
        logging.error("Could not extract node IP from experiment manifests")
        sys.exit(1)
    
    # Use SSH to connect to the deploy node and run 'hostname'.
    ssh_cmd = [
        "ssh",
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
