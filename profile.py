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

node.addService(pg.Execute(shell="/bin/sh", command=f"""
until id {USER}; do
  echo 'Waiting for user {USER}...' >> /local/logs/ssh_debug.log
  sleep 2
done

mkdir -p /users/{USER}/.ssh
echo '{params.CLOUDLAB_SSH_PUB_KEY}' > /users/{USER}/.ssh/authorized_keys
chmod 600 /users/{USER}/.ssh/authorized_keys
chown -R {USER}:{USER} /users/{USER}/.ssh

echo 'KEY_INJECTED' > /local/logs/ssh_injection_status.txt
echo 'Resolved USER={USER}' > /local/logs/who_was_user.txt
cat /users/{USER}/.ssh/authorized_keys > /local/logs/authorized_keys.txt
"""))



pc.printRequestRSpec(request)
