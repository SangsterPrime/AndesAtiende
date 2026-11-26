"""Flujo explícito Learner Lab. No crea recursos al importar ni al usar --dry-run."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, WaiterError


REGION = 'us-east-1'
ROOT = Path(__file__).resolve().parents[2]
SKLEARN_VERSION = '1.8.0'
MAX_ARTIFACT = 32 * 1024 * 1024


def names(run_id):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?', run_id):
        raise ValueError('run-id debe tener 1 a 32 caracteres: minúsculas, números y guiones interiores')
    base = f'andes-g5-{run_id}'
    return {'job': f'{base}-train', 'model': f'{base}-model',
            'config': f'{base}-serverless', 'endpoint': f'{base}-endpoint'}


def prefix(run_id):
    names(run_id)
    return f'andesatiende/ep3/{run_id}'


def bucket_name(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value):
        raise ValueError('Indica el nombre de un bucket S3 existente, no una URI')
    return value


def check_bucket(s3, bucket):
    bucket_name(bucket)
    if s3.get_bucket_location(Bucket=bucket).get('LocationConstraint') not in (None, REGION):
        raise ValueError('El bucket debe estar en us-east-1')


def image_uri(value):
    if not re.fullmatch(r'\d{12}\.dkr\.ecr\.us-east-1\.amazonaws\.com/[a-z0-9][a-z0-9_./-]*@sha256:[a-f0-9]{64}', value):
        raise ValueError('Se requiere imagen ECR privada de us-east-1 fijada por @sha256:..., no un tag mutable')
    return value


def lab_role(value):
    if not re.fullmatch(r'arn:aws:iam::\d{12}:role/(?:[\w+=,.@-]+/)*LabRole', value):
        raise ValueError('Usa el ARN real del rol existente LabRole; no se crean roles IAM')
    return value


def prepare_tickets(path):
    path = Path(path)
    if path.name != 'tickets.csv':
        raise ValueError('El archivo tratado debe llamarse tickets.csv')
    data = path.read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    if not {'texto_consulta', 'categoria'}.issubset(reader.fieldnames or []):
        raise ValueError('Faltan texto_consulta/categoria en los tickets tratados')
    count = sum(1 for row in reader if row.get('categoria') and len(row.get('texto_consulta') or '') >= 3)
    if not count:
        raise ValueError('No hay tickets válidos')
    return data, hashlib.sha256(data).hexdigest(), count


def upload(s3, bucket, run_id, tickets):
    data, digest, count = prepare_tickets(tickets)
    key = f'{prefix(run_id)}/train/tickets.csv'
    check_bucket(s3, bucket)
    # Evita reemplazar datos de una ejecución anterior; no cambia ACL ni políticas.
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType='text/csv',
                  ServerSideEncryption='AES256', Metadata={'sha256': digest}, IfNoneMatch='*')
    return {'s3_train': f's3://{bucket}/{key}', 'sha256': digest, 'tickets_validos': count}


def training_request(bucket, run_id, image, role, version, minimum=.85, instance='ml.m5.large'):
    bucket_name(bucket)
    if not version.strip() or len(version) > 128:
        raise ValueError('model-version debe tener entre 1 y 128 caracteres')
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError('min-f1 debe estar entre 0 y 1')
    if instance not in ('ml.m5.large', 'ml.m5.xlarge', 'ml.m5.2xlarge'):
        raise ValueError('Tipo de instancia CPU no admitido por este flujo')
    return {
        'TrainingJobName': names(run_id)['job'], 'RoleArn': lab_role(role),
        'AlgorithmSpecification': {'TrainingImage': image_uri(image), 'TrainingInputMode': 'File'},
        'HyperParameters': {'min-f1': str(minimum), 'model-version': version},
        'InputDataConfig': [{
            'ChannelName': 'train', 'ContentType': 'text/csv', 'InputMode': 'File',
            'DataSource': {'S3DataSource': {'S3DataType': 'S3Prefix',
                'S3Uri': f's3://{bucket}/{prefix(run_id)}/train/tickets.csv',
                'S3DataDistributionType': 'FullyReplicated'}},
        }],
        'OutputDataConfig': {'S3OutputPath': f's3://{bucket}/{prefix(run_id)}/output'},
        'ResourceConfig': {'InstanceType': instance, 'InstanceCount': 1, 'VolumeSizeInGB': 10},
        'StoppingCondition': {'MaxRuntimeInSeconds': 600},
        'EnableNetworkIsolation': True,
        'Tags': [{'Key': 'proyecto', 'Value': 'andesatiende-ep3-grupo5'}],
    }


def start_training(sm, s3, request, wait=False):
    uri = urlparse(request['InputDataConfig'][0]['DataSource']['S3DataSource']['S3Uri'])
    check_bucket(s3, uri.netloc)
    source = s3.head_object(Bucket=uri.netloc, Key=uri.path.lstrip('/'))
    if not source.get('ContentLength') or not re.fullmatch(r'[a-f0-9]{64}', source.get('Metadata', {}).get('sha256', '')):
        raise ValueError('Falta un tickets.csv cargado por el paso upload (con hash SHA-256)')
    sm.create_training_job(**request)
    result = {'training_job': request['TrainingJobName']}
    if wait:
        sm.get_waiter('training_job_completed_or_stopped').wait(
            TrainingJobName=request['TrainingJobName'], WaiterConfig={'Delay': 30, 'MaxAttempts': 80})
        job = sm.describe_training_job(TrainingJobName=request['TrainingJobName'])
        if job['TrainingJobStatus'] != 'Completed':
            raise ValueError(f"Training Job no completado: {job['TrainingJobStatus']}")
        result['model_artifact'] = job['ModelArtifacts']['S3ModelArtifacts']
    return result


def validate_artifact(data, version, minimum):
    if not math.isfinite(minimum) or not 0 <= minimum <= 1:
        raise ValueError('Umbral de calidad inválido')
    if len(data) > MAX_ARTIFACT:
        raise ValueError('Artefacto demasiado grande para este clasificador')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        files = {}
        for member in archive.getmembers():
            if member.isdir():
                continue
            name = str(PurePosixPath(member.name))
            if (not member.isfile() or name not in ('clasificador.joblib', 'metadata.json')
                    or name in files or member.size > MAX_ARTIFACT or member.size <= 0):
                raise ValueError('Contenido inesperado en model.tar.gz')
            files[name] = member
        if set(files) != {'clasificador.joblib', 'metadata.json'}:
            raise ValueError('Falta clasificador.joblib o metadata.json en la raíz del artefacto')
        if files['metadata.json'].size > 1024 * 1024:
            raise ValueError('Metadata demasiado grande')
        metadata = json.load(archive.extractfile(files['metadata.json']))
    if not isinstance(metadata, dict):
        raise ValueError('Metadata debe ser un objeto JSON')
    if metadata.get('version_sklearn') != SKLEARN_VERSION or metadata.get('version_modelo') != version:
        raise ValueError('Versión de modelo/dependencias incompatible con el Training Job')
    score = metadata.get('macro_f1')
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not minimum <= score <= 1:
        raise ValueError('El artefacto no supera el quality gate esperado')
    return metadata


def deploy(sm, s3, run_id, memory=2048, concurrency=1, wait=False):
    resource = names(run_id)
    if memory not in (1024, 2048, 3072, 4096, 5120, 6144) or not 1 <= concurrency <= 200:
        raise ValueError('Configuración serverless inválida')
    job = sm.describe_training_job(TrainingJobName=resource['job'])
    if job['TrainingJobStatus'] != 'Completed':
        raise ValueError('Se requiere un Training Job Completed antes de desplegar')
    image = image_uri(job['AlgorithmSpecification']['TrainingImage'])
    role = lab_role(job['RoleArn'])
    artifact = job['ModelArtifacts']['S3ModelArtifacts']
    uri = urlparse(artifact)
    if uri.scheme != 's3' or not uri.netloc or not uri.path.endswith('.tar.gz'):
        raise ValueError('S3ModelArtifacts no es una URI S3 tar.gz válida')
    check_bucket(s3, uri.netloc)
    response = s3.get_object(Bucket=uri.netloc, Key=uri.path.lstrip('/'))
    try:
        data = response['Body'].read(MAX_ARTIFACT + 1)
    finally:
        response['Body'].close()
    metadata = validate_artifact(data, job['HyperParameters']['model-version'], float(job['HyperParameters']['min-f1']))
    # Reutiliza el digest exacto y el artefacto real devueltos por el Training Job.
    sm.create_model(ModelName=resource['model'], ExecutionRoleArn=role,
                    PrimaryContainer={'Image': image, 'ModelDataUrl': artifact})
    sm.create_endpoint_config(EndpointConfigName=resource['config'], ProductionVariants=[{
        'VariantName': 'AllTraffic', 'ModelName': resource['model'],
        'ServerlessConfig': {'MemorySizeInMB': memory, 'MaxConcurrency': concurrency},
    }])
    sm.create_endpoint(EndpointName=resource['endpoint'], EndpointConfigName=resource['config'])
    if wait:
        sm.get_waiter('endpoint_in_service').wait(EndpointName=resource['endpoint'],
                                                WaiterConfig={'Delay': 30, 'MaxAttempts': 80})
    return {'endpoint': resource['endpoint'], 'version_modelo': metadata['version_modelo'],
            'estado': 'InService' if wait else 'Creación solicitada'}


def invoke(runtime, run_id, mensaje, expected_version):
    text = mensaje.strip()
    if not 3 <= len(text) <= 1200:
        raise ValueError('mensaje debe tener entre 3 y 1200 caracteres')
    response = runtime.invoke_endpoint(EndpointName=names(run_id)['endpoint'], ContentType='application/json',
        Accept='application/json', Body=json.dumps({'mensaje': text}, ensure_ascii=False).encode('utf-8'))
    try:
        data = json.loads(response['Body'].read())
    finally:
        response['Body'].close()
    if not isinstance(data, dict):
        raise ValueError('Respuesta de inferencia inválida')
    probability = data.get('probabilidad')
    if (not isinstance(data.get('intencion'), str) or not data['intencion']
            or data.get('version_modelo') != expected_version
            or not isinstance(probability, (int, float)) or isinstance(probability, bool)
            or not math.isfinite(probability) or not 0 <= probability <= 1):
        raise ValueError('Respuesta de inferencia incompatible o inválida')
    return {key: data[key] for key in ('intencion', 'probabilidad', 'version_modelo')}


def cleanup(sm, run_id):
    resource = names(run_id)
    # Solo nombres derivados de este run-id; no borra S3, ECR, roles ni otros endpoints.
    try:
        sm.describe_endpoint(EndpointName=resource['endpoint'])
    except ClientError as error:
        if error.response['Error']['Code'] != 'ValidationException' or 'Could not find' not in error.response['Error']['Message']:
            raise
    else:
        sm.delete_endpoint(EndpointName=resource['endpoint'])
        sm.get_waiter('endpoint_deleted').wait(EndpointName=resource['endpoint'],
                                             WaiterConfig={'Delay': 20, 'MaxAttempts': 80})
    for method, key, value in ((sm.delete_endpoint_config, 'EndpointConfigName', resource['config']),
                               (sm.delete_model, 'ModelName', resource['model'])):
        try:
            method(**{key: value})
        except ClientError as error:
            if error.response['Error']['Code'] != 'ValidationException' or 'Could not find' not in error.response['Error']['Message']:
                raise
    return {'limpieza_solicitada': resource}


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument('--region', choices=[REGION], default=REGION)
    command.add_argument('--profile', help='Perfil AWS opcional; nunca se lee .env')
    commands = command.add_subparsers(dest='action', required=True)
    up = commands.add_parser('upload', help='Cargar únicamente tickets.csv tratado en un bucket existente')
    up.add_argument('--bucket', required=True)
    up.add_argument('--run-id', required=True)
    up.add_argument('--tickets', type=Path, default=ROOT / 'datos/procesados/tickets.csv')
    up.add_argument('--dry-run', action='store_true')
    train = commands.add_parser('train', help='Crear Training Job con LabRole e imagen por digest')
    train.add_argument('--bucket', required=True)
    train.add_argument('--run-id', required=True)
    train.add_argument('--image-uri', required=True)
    train.add_argument('--role-arn', required=True)
    train.add_argument('--model-version', required=True)
    train.add_argument('--min-f1', type=float, default=.85)
    train.add_argument('--instance-type', default='ml.m5.large')
    train.add_argument('--wait', action='store_true')
    train.add_argument('--dry-run', action='store_true')
    deployment = commands.add_parser('deploy', help='Desplegar solo un job Completed como endpoint serverless')
    deployment.add_argument('--run-id', required=True)
    deployment.add_argument('--memory', type=int, default=2048)
    deployment.add_argument('--concurrency', type=int, default=1)
    deployment.add_argument('--wait', action='store_true')
    prediction = commands.add_parser('invoke', help='Enviar una consulta sintética al endpoint')
    prediction.add_argument('--run-id', required=True)
    prediction.add_argument('--mensaje', required=True)
    prediction.add_argument('--model-version', required=True)
    delete = commands.add_parser('cleanup', help='Borrar únicamente endpoint/config/model de este run-id')
    delete.add_argument('--run-id', required=True)
    delete.add_argument('--confirm', action='store_true', required=True)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    names(args.run_id)
    request = None
    if args.action == 'train':
        request = training_request(args.bucket, args.run_id, args.image_uri, args.role_arn,
                                   args.model_version, args.min_f1, args.instance_type)
    if getattr(args, 'dry_run', False):
        if args.action == 'upload':
            _, digest, count = prepare_tickets(args.tickets)
            bucket_name(args.bucket)
            request = {'s3_train': f's3://{args.bucket}/{prefix(args.run_id)}/train/tickets.csv',
                       'sha256': digest, 'tickets_validos': count}
        print(json.dumps({'dry_run': True, 'request': request}, ensure_ascii=False, indent=2))
        return
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    # Credentials: cadena estándar AWS; incluye AWS_SESSION_TOKEN del Learner Lab.
    def client(service):
        return session.client(service, config=Config(connect_timeout=10, read_timeout=70,
            retries={'mode': 'standard', 'max_attempts': 2}))
    if args.action == 'upload':
        result = upload(client('s3'), args.bucket, args.run_id, args.tickets)
    elif args.action == 'train':
        result = start_training(client('sagemaker'), client('s3'), request, args.wait)
    elif args.action == 'deploy':
        result = deploy(client('sagemaker'), client('s3'), args.run_id, args.memory, args.concurrency, args.wait)
    elif args.action == 'invoke':
        result = invoke(client('sagemaker-runtime'), args.run_id, args.mensaje, args.model_version)
    else:
        result = cleanup(client('sagemaker'), args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, BotoCoreError, ClientError, WaiterError, tarfile.TarError) as error:
        print(f'EP3: {error}', file=sys.stderr)
        raise SystemExit(1)
