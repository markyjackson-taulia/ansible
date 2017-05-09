Playbooks to launch AWS infrastructure.

Steps:

Edit vars/aws-creds.yml to include your own AWS credentials
Edit vars/dev-environment.yml to define the security groups, sets of instances, etc, that will be used.
Run: ansible-playbook -i hosts provision.yml
To shut down the infrastructure use the exact_count values in the vars/dev-environment.yml file to 0 and re-running provision.yml.