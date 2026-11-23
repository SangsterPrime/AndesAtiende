import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tarfile
from unittest.mock import Mock

import boto3
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
import pytest

from scripts.aws import ep3
from scripts.aws.publicar_imagen import publish


BUCKET = 'andesatiende-prueba-g5'
ROLE = 'arn:aws:iam::123456789012:role/LabRole'
IMAGE = '123456789012.dkr.ecr.us-east-1.amazonaws.com/andesatiende-ep3-g5@sha256:' + 'a' * 64
RUN = 'ep3-local-test'
ARTIFACT = f's3://{BUCKET}/output/model.tar.gz'


def client(service):
    # Credenciales ficticias y Stubber: jamás se consulta la cadena real ni AWS.
    return boto3.client(service, region_name=ep3.REGION, aws_access_key_id='testing',
                        aws_secret_access_key='testing', aws_session_token='testing')


def request():
    return ep3.training_request(BUCKET, RUN, IMAGE, ROLE, 'ep3-test')


def job(status='Completed'):
    params = request()
    return {key: params[key] for key in (
        'TrainingJobName', 'RoleArn', 'AlgorithmSpecification', 'HyperParameters',
        'ResourceConfig', 'StoppingCondition', 'OutputDataConfig', 'InputDataConfig',
    )} | {
        'TrainingJobArn': f'arn:aws:sagemaker:us-east-1:123456789012:training-job/{ep3.names(RUN)["job"]}',
        'TrainingJobStatus': status, 'SecondaryStatus': 'Completed',
        'CreationTime': datetime(2026, 11, 23, tzinfo=timezone.utc),
        'ModelArtifacts': {'S3ModelArtifacts': ARTIFACT},
    }


def archive(metadata=None, extra=None):
    metadata = metadata or {'version_sklearn': '1.8.0', 'version_modelo': 'ep3-test', 'macro_f1': .9}
    output = io.BytesIO()
    files = {'metadata.json': json.dumps(metadata).encode(), 'clasificador.joblib': b'fixture-not-loaded'}
    files.update(extra or {})
    with tarfile.open(fileobj=output, mode='w:gz') as bundle:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
    return output.getvalue()


def body(data):
    return StreamingBody(io.BytesIO(data), len(data))


def test_upload_nombre_canal_cifrado_y_no_sobrescritura(tmp_path):
    tickets = tmp_path / 'tickets.csv'
    tickets.write_text('categoria,texto_consulta\nfacturacion,consulta sintetica\n', encoding='utf-8')
    s3 = client('s3')
    with Stubber(s3) as stub:
        stub.add_response('get_bucket_location', {}, {'Bucket': BUCKET})
        stub.add_response('put_object', {}, {'Bucket': BUCKET, 'Key': f'{ep3.prefix(RUN)}/train/tickets.csv',
            'Body': tickets.read_bytes(), 'ContentType': 'text/csv', 'ServerSideEncryption': 'AES256',
            'Metadata': {'sha256': ANY}, 'IfNoneMatch': '*'})
        result = ep3.upload(s3, BUCKET, RUN, tickets)
        assert result['s3_train'].endswith('/train/tickets.csv')
        assert result['tickets_validos'] == 1
        stub.assert_no_pending_responses()


def test_upload_rechaza_otras_regiones(tmp_path):
    tickets = tmp_path / 'tickets.csv'
    tickets.write_text('categoria,texto_consulta\nfacturacion,consulta sintetica\n')
    s3 = client('s3')
    with Stubber(s3) as stub:
        stub.add_response('get_bucket_location', {'LocationConstraint': 'eu-west-1'}, {'Bucket': BUCKET})
        with pytest.raises(ValueError, match='us-east-1'):
            ep3.upload(s3, BUCKET, RUN, tickets)


def test_training_request_y_espera_completed():
    sm, s3 = client('sagemaker'), client('s3')
    params = request()
    assert params['InputDataConfig'][0]['ChannelName'] == 'train'
    assert params['AlgorithmSpecification']['TrainingInputMode'] == 'File'
    assert params['EnableNetworkIsolation'] is True
    assert params['ResourceConfig']['InstanceCount'] == 1
    with Stubber(s3) as s3stub, Stubber(sm) as smstub:
        s3stub.add_response('get_bucket_location', {}, {'Bucket': BUCKET})
        s3stub.add_response('head_object', {'ContentLength': 10, 'Metadata': {'sha256': 'a' * 64}},
                           {'Bucket': BUCKET, 'Key': f'{ep3.prefix(RUN)}/train/tickets.csv'})
        smstub.add_response('create_training_job', {'TrainingJobArn': job()['TrainingJobArn']}, params)
        smstub.add_response('describe_training_job', job(), {'TrainingJobName': params['TrainingJobName']})
        smstub.add_response('describe_training_job', job(), {'TrainingJobName': params['TrainingJobName']})
        assert ep3.start_training(sm, s3, params, wait=True)['model_artifact'] == ARTIFACT
        s3stub.assert_no_pending_responses()
        smstub.assert_no_pending_responses()


@pytest.mark.parametrize('patch', [
    {'image': IMAGE.replace('us-east-1', 'us-west-2')},
    {'image': IMAGE.split('@')[0] + ':latest'}, {'role': ROLE.replace('LabRole', 'Admin')},
    {'run_id': '../otro'}, {'minimum': float('nan')}, {'minimum': 1.1}, {'version': ''},
    {'instance': 'ml.p4d.24xlarge'},
])
def test_rechaza_configuracion_peligrosa(patch):
    values = dict(bucket=BUCKET, run_id=RUN, image=IMAGE, role=ROLE, version='ep3-test') | patch
    with pytest.raises(ValueError):
        ep3.training_request(**values)


def test_deploy_usa_digest_y_artefacto_del_job_y_solo_serverless():
    sm, s3 = client('sagemaker'), client('s3')
    resources = ep3.names(RUN)
    with Stubber(sm) as smstub, Stubber(s3) as s3stub:
        smstub.add_response('describe_training_job', job(), {'TrainingJobName': resources['job']})
        s3stub.add_response('get_bucket_location', {}, {'Bucket': BUCKET})
        s3stub.add_response('get_object', {'Body': body(archive())}, {'Bucket': BUCKET, 'Key': 'output/model.tar.gz'})
        smstub.add_response('create_model', {'ModelArn': 'arn:aws:sagemaker:us-east-1:123456789012:model/test'}, {
            'ModelName': resources['model'], 'ExecutionRoleArn': ROLE,
            'PrimaryContainer': {'Image': IMAGE, 'ModelDataUrl': ARTIFACT}})
        smstub.add_response('create_endpoint_config', {
            'EndpointConfigArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint-config/test'}, {
            'EndpointConfigName': resources['config'], 'ProductionVariants': [{
                'VariantName': 'AllTraffic', 'ModelName': resources['model'],
                'ServerlessConfig': {'MemorySizeInMB': 2048, 'MaxConcurrency': 1},
            }]})
        smstub.add_response('create_endpoint', {'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint/test'}, {
            'EndpointName': resources['endpoint'], 'EndpointConfigName': resources['config']})
        assert ep3.deploy(sm, s3, RUN)['version_modelo'] == 'ep3-test'
        smstub.assert_no_pending_responses()
        s3stub.assert_no_pending_responses()


@pytest.mark.parametrize('status', ['Failed', 'Stopped', 'InProgress'])
def test_no_despliega_job_sin_completar(status):
    sm = client('sagemaker')
    with Stubber(sm) as stub:
        stub.add_response('describe_training_job', job(status), {'TrainingJobName': ep3.names(RUN)['job']})
        with pytest.raises(ValueError, match='Completed'):
            ep3.deploy(sm, Mock(), RUN)


@pytest.mark.parametrize('metadata', [
    {'version_sklearn': '1.2.1', 'version_modelo': 'ep3-test', 'macro_f1': .99},
    {'version_sklearn': '1.8.0', 'version_modelo': 'ep2', 'macro_f1': .99},
    {'version_sklearn': '1.8.0', 'version_modelo': 'ep3-test', 'macro_f1': .2},
    {'version_sklearn': '1.8.0', 'version_modelo': 'ep3-test', 'macro_f1': float('nan')},
])
def test_rechaza_artefacto_incompatible(metadata):
    with pytest.raises(ValueError):
        ep3.validate_artifact(archive(metadata), 'ep3-test', .85)


@pytest.mark.parametrize('name', ['../outside', '/metadata.json', 'code/inference.py'])
def test_no_extrae_archivos_arbitrarios(name):
    with pytest.raises(ValueError, match='Contenido inesperado'):
        ep3.validate_artifact(archive(extra={name: b'invalid'}), 'ep3-test', .85)


def test_invoke_envia_mensaje_y_valida_probabilidad_version():
    runtime = client('sagemaker-runtime')
    result = {'intencion': 'falla_conexion', 'probabilidad': .91, 'version_modelo': 'ep3-test'}
    with Stubber(runtime) as stub:
        stub.add_response('invoke_endpoint', {'Body': body(json.dumps(result).encode()), 'ContentType': 'application/json'}, {
            'EndpointName': ep3.names(RUN)['endpoint'], 'ContentType': 'application/json', 'Accept': 'application/json',
            'Body': json.dumps({'mensaje': 'No tengo internet'}, ensure_ascii=False).encode()})
        assert ep3.invoke(runtime, RUN, 'No tengo internet', 'ep3-test') == result


@pytest.mark.parametrize('patch', [{'probabilidad': 2}, {'probabilidad': True}, {'probabilidad': float('nan')},
                                  {'version_modelo': 'ep2'}, {'intencion': ''}])
def test_invoke_no_acepta_resultados_invalidos(patch):
    runtime = Mock()
    result = {'intencion': 'falla_conexion', 'probabilidad': .91, 'version_modelo': 'ep3-test'} | patch
    runtime.invoke_endpoint.return_value = {'Body': body(json.dumps(result).encode())}
    with pytest.raises(ValueError):
        ep3.invoke(runtime, RUN, 'consulta', 'ep3-test')


def test_dry_run_y_help_no_inician_sesion_aws(monkeypatch, capsys):
    monkeypatch.setattr(ep3.boto3, 'Session', lambda **kwargs: pytest.fail('No debe contactar AWS'))
    ep3.main(['train', '--bucket', BUCKET, '--run-id', RUN, '--image-uri', IMAGE,
              '--role-arn', ROLE, '--model-version', 'ep3-test', '--dry-run'])
    assert json.loads(capsys.readouterr().out)['dry_run'] is True
    with pytest.raises(SystemExit) as error:
        ep3.main(['--help'])
    assert error.value.code == 0


def test_publicacion_imagen_usa_stdin_y_devuelve_digest_inmutable():
    ecr = client('ecr')
    repository = {'repositoryArn': 'arn:aws:ecr:us-east-1:123456789012:repository/test',
                  'registryId': '123456789012', 'repositoryName': 'test',
                  'repositoryUri': '123456789012.dkr.ecr.us-east-1.amazonaws.com/test'}
    runner = Mock()
    with Stubber(ecr) as stub:
        stub.add_response('describe_repositories', {'repositories': [repository]}, {'repositoryNames': ['test']})
        stub.add_response('get_authorization_token', {'authorizationData': [{
            'authorizationToken': base64.b64encode(b'AWS:fake-token').decode(),
            'proxyEndpoint': 'https://123456789012.dkr.ecr.us-east-1.amazonaws.com',
        }]}, {'registryIds': ['123456789012']})
        stub.add_response('describe_images', {'imageDetails': [{'imageDigest': 'sha256:' + 'b' * 64}]},
                          {'repositoryName': 'test', 'imageIds': [{'imageTag': 'ep3-test'}]})
        result = publish(ecr, 'test', 'ep3-test', run=runner)
        assert result['image_uri'].endswith('@sha256:' + 'b' * 64)
    assert runner.call_args_list[0].args[0][1:4] == ['build', '--platform', 'linux/amd64']
    login = runner.call_args_list[1]
    assert '--password-stdin' in login.args[0]
    assert 'fake-token' not in str(login.args[0])
    assert login.kwargs['input'] == 'fake-token'


def test_dependencias_y_contexto_docker_no_incluyen_secretos():
    root = Path(__file__).resolve().parents[3]
    requirements = (root / 'servicio-ia/requirements.txt').read_text()
    assert f'scikit-learn=={ep3.SKLEARN_VERSION}' in requirements
    docker = '\n'.join(line for line in (root / 'servicio-ia/Dockerfile.sagemaker').read_text().splitlines()
                       if not line.lstrip().startswith('#'))
    assert 'python:3.12-slim' in docker and 'ENTRYPOINT' in docker
    assert 'COPY . ' not in docker
    assert 'modelo/' not in docker and '.env ' not in docker


def test_training_stopped_no_se_considera_exito():
    sm, s3 = client('sagemaker'), client('s3')
    params = request()
    with Stubber(s3) as s3stub, Stubber(sm) as smstub:
        s3stub.add_response('get_bucket_location', {}, {'Bucket': BUCKET})
        s3stub.add_response('head_object', {'ContentLength': 10, 'Metadata': {'sha256': 'a' * 64}},
                           {'Bucket': BUCKET, 'Key': f'{ep3.prefix(RUN)}/train/tickets.csv'})
        smstub.add_response('create_training_job', {'TrainingJobArn': job()['TrainingJobArn']}, params)
        smstub.add_response('describe_training_job', job('Stopped'), {'TrainingJobName': params['TrainingJobName']})
        smstub.add_response('describe_training_job', job('Stopped'), {'TrainingJobName': params['TrainingJobName']})
        with pytest.raises(ValueError, match='Stopped'):
            ep3.start_training(sm, s3, params, wait=True)


def test_artefacto_invalido_impide_crear_recursos():
    sm, s3 = client('sagemaker'), client('s3')
    with Stubber(sm) as smstub, Stubber(s3) as s3stub:
        smstub.add_response('describe_training_job', job(), {'TrainingJobName': ep3.names(RUN)['job']})
        s3stub.add_response('get_bucket_location', {}, {'Bucket': BUCKET})
        s3stub.add_response('get_object', {'Body': body(archive(extra={'malicious': b'bad'}))},
                           {'Bucket': BUCKET, 'Key': 'output/model.tar.gz'})
        with pytest.raises(ValueError, match='Contenido inesperado'):
            ep3.deploy(sm, s3, RUN)
        smstub.assert_no_pending_responses()


def test_cleanup_espera_endpoint_y_borra_solo_nombres_del_run():
    sm = client('sagemaker')
    resource = ep3.names(RUN)
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    with Stubber(sm) as stub:
        stub.add_response('describe_endpoint', {
            'EndpointName': resource['endpoint'], 'EndpointArn': 'arn:aws:sagemaker:us-east-1:123456789012:endpoint/test',
            'EndpointConfigName': resource['config'], 'EndpointStatus': 'InService',
            'CreationTime': now, 'LastModifiedTime': now,
        }, {'EndpointName': resource['endpoint']})
        stub.add_response('delete_endpoint', {}, {'EndpointName': resource['endpoint']})
        stub.add_client_error('describe_endpoint', 'ValidationException', 'Could not find endpoint',
                              expected_params={'EndpointName': resource['endpoint']})
        stub.add_response('delete_endpoint_config', {}, {'EndpointConfigName': resource['config']})
        stub.add_response('delete_model', {}, {'ModelName': resource['model']})
        assert ep3.cleanup(sm, RUN)['limpieza_solicitada'] == resource
        stub.assert_no_pending_responses()


def test_cleanup_de_recursos_ausentes_no_toca_otros():
    sm = client('sagemaker')
    resource = ep3.names(RUN)
    with Stubber(sm) as stub:
        for method, key, value in [('describe_endpoint', 'EndpointName', resource['endpoint']),
                                   ('delete_endpoint_config', 'EndpointConfigName', resource['config']),
                                   ('delete_model', 'ModelName', resource['model'])]:
            stub.add_client_error(method, 'ValidationException', 'Could not find resource', expected_params={key: value})
        ep3.cleanup(sm, RUN)
        stub.assert_no_pending_responses()


def test_cleanup_no_oculta_access_denied():
    sm = client('sagemaker')
    with Stubber(sm) as stub:
        stub.add_client_error('describe_endpoint', 'AccessDeniedException', 'Denied',
                              expected_params={'EndpointName': ep3.names(RUN)['endpoint']})
        from botocore.exceptions import ClientError
        with pytest.raises(ClientError):
            ep3.cleanup(sm, RUN)


def test_cleanup_requiere_confirmacion_cli(monkeypatch):
    monkeypatch.setattr(ep3.boto3, 'Session', lambda **kwargs: pytest.fail('No iniciar AWS sin confirmar'))
    with pytest.raises(SystemExit) as error:
        ep3.main(['cleanup', '--run-id', RUN])
    assert error.value.code == 2


def test_publicacion_no_crea_repositorio_sin_opt_in():
    ecr = client('ecr')
    runner = Mock()
    with Stubber(ecr) as stub:
        stub.add_client_error('describe_repositories', 'RepositoryNotFoundException', 'Not found',
                              expected_params={'repositoryNames': ['test']})
        with pytest.raises(ValueError, match='--create-repository'):
            publish(ecr, 'test', 'ep3-test', run=runner)
    assert runner.call_count == 1  # Solo build local; nada de login/push.
