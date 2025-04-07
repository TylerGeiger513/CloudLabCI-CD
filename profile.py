import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.igext as IG

# Define profile parameters
pc = portal.Context()
pc.defineParameter(
    name="CLOUDLAB_SSH_PUB_KEY",
    description="SSH Public Key to allow access",
    typ=portal.ParameterType.STRING,
    default=""
)
params = pc.bindParameters()  # ✅ Bind parameter values

# Create RSpec
request = pc.makeRequestRSpec()

# Tour description (optional)
tourDescription = """
This profile spins up a node, installs Docker, Minikube, Skaffold, kubectl, and deploys the app automatically using skaffold.
"""
tour = IG.Tour()
tour.Description(IG.Tour.TEXT, tourDescription)
request.addTour(tour)

# Define the node
node = request.RawPC("deploy-node")
node.hardware_type = "d430"
node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU22-64-STD"
node.routable_control_ip = True

# Add blockstore
bs = node.Blockstore("bs", "/mydata")
bs.size = "20GB"

# Inject SSH key at startup
node.addService(pg.Execute(shell="sh", command=f"""
#!/bin/bash
USER=ubuntu
mkdir -p /home/$USER/.ssh
echo '{params.CLOUDLAB_SSH_PUB_KEY}' > /home/$USER/.ssh/authorized_keys
chmod 600 /home/$USER/.ssh/authorized_keys
chown -R $USER:$USER /home/$USER/.ssh
echo "KEY_INJECTED" > /local/logs/ssh_injection_status.txt
cat /home/$USER/.ssh/authorized_keys > /local/logs/authorized_keys.txt
"""))

# Output RSpec
pc.printRequestRSpec(request)
