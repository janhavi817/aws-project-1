import boto3
import time
import urllib.request

def get_latest_ami(ssm_client):
    try:
        # Fetch the latest Amazon Linux 2 AMI from SSM Parameter Store
        response = ssm_client.get_parameter(Name='/aws/service/ami-amazon-linux-latest/amzn2-ami-hvm-x86_64-gp2')
        return response['Parameter']['Value']
    except Exception as e:
        print(f"Error fetching AMI: {e}")
        return None

def deploy_scalable_architecture():
    ec2 = boto3.client('ec2', region_name='ap-south-1')
    elbv2 = boto3.client('elbv2', region_name='ap-south-1')
    autoscaling = boto3.client('autoscaling', region_name='ap-south-1')
    ssm = boto3.client('ssm', region_name='ap-south-1')

    print("Starting Scalable Web App Deployment...")

    # 1. Get Default VPC and Subnets
    vpcs = ec2.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])
    vpc_id = vpcs['Vpcs'][0]['VpcId']
    
    subnets = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])
    subnet_ids = [subnet['SubnetId'] for subnet in subnets['Subnets']][:2] # Need at least 2 subnets for ALB

    # 2. Create Security Group for ALB (Allows internet traffic to Port 80)
    try:
        alb_sg = ec2.create_security_group(
            GroupName='ALB-Web-SG',
            Description='Allow HTTP traffic to ALB',
            VpcId=vpc_id
        )
        alb_sg_id = alb_sg['GroupId']
        ec2.authorize_security_group_ingress(
            GroupId=alb_sg_id,
            IpPermissions=[{'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}]
        )
        print("[OK] ALB Security Group created.")
    except Exception as e:
        if 'InvalidGroup.Duplicate' in str(e):
            print("[INFO] ALB Security Group already exists. Fetching its ID...")
            sgs = ec2.describe_security_groups(GroupNames=['ALB-Web-SG'])
            alb_sg_id = sgs['SecurityGroups'][0]['GroupId']
        else:
            raise e

    # 3. Create Security Group for EC2 Auto Scaling Group (Allows HTTP only from ALB)
    try:
        asg_sg = ec2.create_security_group(
            GroupName='ASG-Web-SG',
            Description='Allow HTTP traffic from ALB to EC2 instances',
            VpcId=vpc_id
        )
        asg_sg_id = asg_sg['GroupId']
        ec2.authorize_security_group_ingress(
            GroupId=asg_sg_id,
            IpPermissions=[{'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'UserIdGroupPairs': [{'GroupId': alb_sg_id}]}]
        )
        print("[OK] Auto Scaling Group Security Group created.")
    except Exception as e:
        if 'InvalidGroup.Duplicate' in str(e):
            print("[INFO] ASG Security Group already exists. Fetching its ID...")
            sgs = ec2.describe_security_groups(GroupNames=['ASG-Web-SG'])
            asg_sg_id = sgs['SecurityGroups'][0]['GroupId']
        else:
            raise e

    # 4. Create Target Group
    try:
        target_group = elbv2.create_target_group(
            Name='Scalable-Web-TG',
            Protocol='HTTP',
            Port=80,
            VpcId=vpc_id,
            TargetType='instance',
            HealthCheckPath='/'
        )
        tg_arn = target_group['TargetGroups'][0]['TargetGroupArn']
        print("[OK] Target Group created.")
    except Exception as e:
        if 'DuplicateTargetGroupName' in str(e):
            print("[INFO] Target Group already exists.")
            tgs = elbv2.describe_target_groups(Names=['Scalable-Web-TG'])
            tg_arn = tgs['TargetGroups'][0]['TargetGroupArn']
        else:
            raise e

    # 5. Create Application Load Balancer
    alb_arn = None
    alb_dns = None
    try:
        alb = elbv2.create_load_balancer(
            Name='Scalable-Web-ALB',
            Subnets=subnet_ids,
            SecurityGroups=[alb_sg_id],
            Scheme='internet-facing',
            Type='application',
            IpAddressType='ipv4'
        )
        alb_arn = alb['LoadBalancers'][0]['LoadBalancerArn']
        alb_dns = alb['LoadBalancers'][0]['DNSName']
        print("[OK] Application Load Balancer created.")
        
        # Create Listener for ALB -> Target Group
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol='HTTP',
            Port=80,
            DefaultActions=[{'Type': 'forward', 'TargetGroupArn': tg_arn}]
        )
        print("[OK] ALB Listener created.")

    except Exception as e:
        if 'DuplicateLoadBalancerName' in str(e):
            print("[INFO] Load Balancer already exists.")
            albs = elbv2.describe_load_balancers(Names=['Scalable-Web-ALB'])
            alb_arn = albs['LoadBalancers'][0]['LoadBalancerArn']
            alb_dns = albs['LoadBalancers'][0]['DNSName']
        else:
            raise e

    # 6. Create Launch Template with Apache Web Server
    user_data = """#!/bin/bash
yum install -y httpd
systemctl start httpd
systemctl enable httpd
TOKEN=$(curl -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
INSTANCE_ID=$(curl -H "X-aws-ec2-metadata-token: $TOKEN" -v http://169.254.169.254/latest/meta-data/instance-id)
echo "<h1>Scalable Web App!</h1><p>You are being served by EC2 Instance: <b>$INSTANCE_ID</b></p><p>Refresh the page to see the Load Balancer distribute traffic to other instances!</p>" > /var/www/html/index.html
"""
    try:
        from base64 import b64encode
        encoded_user_data = b64encode(user_data.encode()).decode()
        
        ami_id = get_latest_ami(ssm)
        
        response = ec2.create_launch_template(
            LaunchTemplateName='Scalable-App-LT',
            LaunchTemplateData={
                'ImageId': ami_id,
                'InstanceType': 't3.micro', # Using t3.micro to bypass your account limits
                'SecurityGroupIds': [asg_sg_id],
                'UserData': encoded_user_data
            }
        )
        lt_id = response['LaunchTemplate']['LaunchTemplateId']
        print("[OK] Launch Template created.")
    except Exception as e:
        if 'InvalidLaunchTemplateName.AlreadyExistsException' in str(e):
            print("[INFO] Launch Template already exists.")
        else:
            raise e

    # 7. Create Auto Scaling Group
    try:
        autoscaling.create_auto_scaling_group(
            AutoScalingGroupName='Scalable-App-ASG',
            LaunchTemplate={
                'LaunchTemplateName': 'Scalable-App-LT',
                'Version': '$Latest'
            },
            MinSize=2,
            MaxSize=4,
            DesiredCapacity=2,
            VPCZoneIdentifier=",".join(subnet_ids),
            TargetGroupARNs=[tg_arn]
        )
        print("[OK] Auto Scaling Group created. (Spinning up 2 EC2 instances automatically!)")
        
        # 8. Create Target Tracking Scaling Policy (CPU Utilization > 50%)
        autoscaling.put_scaling_policy(
            AutoScalingGroupName='Scalable-App-ASG',
            PolicyName='CPU-Target-Tracking-Policy',
            PolicyType='TargetTrackingScaling',
            TargetTrackingConfiguration={
                'PredefinedMetricSpecification': {
                    'PredefinedMetricType': 'ASGAverageCPUUtilization'
                },
                'TargetValue': 50.0,
                'DisableScaleIn': False
            }
        )
        print("[OK] Target Tracking Scaling Policy applied (Scale out when CPU > 50%).")
        
    except Exception as e:
        if 'AlreadyExists' in str(e):
            print("[INFO] Auto Scaling Group already exists.")
        else:
            raise e

    print("\nDeployment Triggered Successfully!")
    print("="*60)
    print("It will take about 3-5 minutes for the EC2 instances to boot and register with the Load Balancer.")
    print(f"Access your scalable app here: http://{alb_dns}")
    print("="*60)

if __name__ == "__main__":
    deploy_scalable_architecture()
