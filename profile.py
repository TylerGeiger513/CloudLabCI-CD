import geni.portal as portal
import geni.rspec.pg as pg
import geni.rspec.igext as IG

pc = portal.Context()
pc.defineParameter(
    name="CLOUDLAB_SSH_PUB_KEY_B64",
    description="Base64-encoded SSH Public Key",
    typ=portal.ParameterType.STRING,
    default=""
)
params = pc.bindParameters()
request = pc.makeRequestRSpec()

tour = IG.Tour()
tour.Description(IG.Tour.TEXT, """
This profile spins up a node, installs Docker, Minikube, Skaffold, kubectl, and deploys the app automatically using skaffold.
""")
request.addTour(tour)

node = request.RawPC("deploy-node")
node.hardware_type = "d430"
node.disk_image = "urn:publicid:IDN+emulab.net+image+emulab-ops:UBUNTU22-64-STD"
node.routable_control_ip = True

bs = node.Blockstore("bs", "/mydata")
bs.size = "20GB"

node.addService(pg.Execute(shell="sh", command=f"""
#!/bin/bash
USER="tg996676"
echo '{params.CLOUDLAB_SSH_PUB_KEY}' | tee /home/$USER/.ssh/authorized_keys /local/logs/authorized_keys.txt
chmod 600 /home/$USER/.ssh/authorized_keys
echo "Resolved USER=$USER" > /local/logs/who_was_user.txt
"""))


pc.printRequestRSpec(request)
