# Scalable Web App with ALB and Auto Scaling

This project automatically deploys a highly available, fault-tolerant web application using AWS Boto3. By executing the architecture script, the logic will programmatically stitch together compute and networking resources to ensure traffic load balancing.

## Architecture Let's Build:
1. **Security Groups**: 
   - `ALB-Web-SG`: Bouncer that only allows port 80 (HTTP) traffic from the global internet.
   - `ASG-Web-SG`: Bouncer assigned strictly to the EC2 instances that ONLY accepts traffic originating from the ALB (preventing bypass attacks).
2. **Launch Template (`Scalable-App-LT`)**: Defines exactly what an EC2 instance should look like, leveraging a dynamically fetched Amazon Linux 2 AMI and a User Data script that installs an Apache HTTP server serving a dynamic HTML page displaying the Instance ID.
3. **Application Load Balancer (`Scalable-Web-ALB`)**: Spans across two Availability Zones in the default VPC, listening for traffic on port 80.
4. **Auto Scaling Group (`Scalable-App-ASG`)**: Dictates a minimum of 2 instances and a max of 4. Automatically places the spun-up instances into the Application Load Balancer's **Target Group**.

## Start the Project
No need to manually install dependencies or configure networking across menus. By running the python file, the infrastructure creates itself gracefully. 

Run:
```powershell
python deploy_infrastructure.py
```

Wait 3-5 minutes for instances to initialize. You will be provided an ALB DNS URL at the end. Refresh the webpage multiple times to see the Application Load Balancer perfectly bounce your request from one EC2 Server to the other!
