import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.igext as IG

# Define profile parameters
pc = portal.Context()
params = pc.defineParameter(
    name="CLOUDLAB_SSH_PUB_KEY",
    description="SSH Public Key to allow access",
    typ=portal.ParameterType.STRING,
    default=""
)
pc.verifyParameters()
request = pc.makeRequestRSpec()

# Add tour description
tourDescription = \
"""
This profile spins up a node, installs Docker, Minikube, Skaffold, kubectl, and deploys the app automatically using skaffold.
"""
tour = IG.Tour()
tour.Description(IG.Tour.TEXT, tourDescription)
request.addTour(tour)

# Define node
node = request.RawPC("deploy-node")
node.hardware_type = "d430"
node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU22-64-STD"
node.routable_control_ip = True

# Add a blockstore
bs = node.Blockstore("bs", "/mydata")
bs.size = "20GB"

# Get the SSH public key from the experiment parameters
pub_key = params.value

# Add startup script to inject SSH key
node.addService(pg.Execute(shell="sh", command=f"""
#!/bin/bash
USER=ubuntu
mkdir -p /home/$USER/.ssh
echo '{pub_key}' >> /home/$USER/.ssh/authorized_keys
chmod 600 /home/$USER/.ssh/authorized_keys
chown -R $USER:$USER /home/$USER/.ssh
echo '{pub_key}' > /local/logs/injected_key.txt
"""))

# Output the request RSpec
pc.printRequestRSpec(request)
