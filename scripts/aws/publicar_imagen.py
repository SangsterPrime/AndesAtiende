"""Build local linux/amd64 + publicación explícita ECR. Nunca se ejecuta al importar."""
import argparse
import base64
import json
import re
import subprocess
import sys

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .ep3 import REGION, ROOT


def publish(ecr, repository, tag, create=False, run=subprocess.run):
    if not re.fullmatch(r'[a-z0-9]+(?:[._/-][a-z0-9]+)*', repository):
        raise ValueError('Nombre de repositorio ECR inválido')
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
        raise ValueError('Tag inválido')
    run(['docker', 'build', '--platform', 'linux/amd64', '--provenance=false', '--sbom=false',
         '-f', 'servicio-ia/Dockerfile.sagemaker',
         '-t', f'andesatiende-ep3:{tag}', '.'], cwd=ROOT, check=True, stdout=sys.stderr)
    try:
        repo = ecr.describe_repositories(repositoryNames=[repository])['repositories'][0]
    except ecr.exceptions.RepositoryNotFoundException:
        if not create:
            raise ValueError('No existe el repositorio ECR; usa --create-repository si el Lab lo permite')
        repo = ecr.create_repository(repositoryName=repository, imageTagMutability='IMMUTABLE',
                                     imageScanningConfiguration={'scanOnPush': True})['repository']
    registry = repo['repositoryUri'].split('/')[0]
    token = ecr.get_authorization_token(registryIds=[repo['registryId']])['authorizationData'][0]
    username, password = base64.b64decode(token['authorizationToken']).decode('utf-8').split(':', 1)
    try:
        run(['docker', 'login', '--username', username, '--password-stdin', registry],
            input=password, text=True, check=True, stdout=sys.stderr)
        image = f"{repo['repositoryUri']}:{tag}"
        run(['docker', 'tag', f'andesatiende-ep3:{tag}', image], check=True, stdout=sys.stderr)
        run(['docker', 'push', image], check=True, stdout=sys.stderr)
        digest = ecr.describe_images(repositoryName=repository, imageIds=[{'imageTag': tag}])['imageDetails'][0]['imageDigest']
    finally:
        run(['docker', 'logout', registry], check=False, capture_output=True)
    return {'image_uri': f"{repo['repositoryUri']}@{digest}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region', choices=[REGION], default=REGION)
    parser.add_argument('--profile')
    parser.add_argument('--repository', default='andesatiende-ep3-g5')
    parser.add_argument('--tag', required=True)
    parser.add_argument('--create-repository', action='store_true')
    args = parser.parse_args(argv)
    ecr = boto3.Session(profile_name=args.profile, region_name=args.region).client('ecr')
    print(json.dumps(publish(ecr, args.repository, args.tag, args.create_repository), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, BotoCoreError, ClientError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'No se publicó la imagen: {error}')
