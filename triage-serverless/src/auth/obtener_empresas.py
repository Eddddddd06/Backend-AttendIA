import boto3
import json
import os

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')


def lambda_handler(event, context):
    """
    PÚBLICO - Sin autenticación requerida.
    Devuelve la lista de empresas (admins) registradas en la plataforma.
    Usado por el formulario público del cliente final para seleccionar
    a qué empresa enviar su ticket.

    Retorna: lista de { tenant_id, nombre_empresa }
    """
    try:
        tabla = dynamodb.Table(TABLE_USUARIOS)

        # Buscar todos los usuarios con rol 'admin' usando el GSI RolIndex
        result = tabla.query(
            IndexName='RolIndex',
            KeyConditionExpression='rol = :rol',
            ExpressionAttributeValues={':rol': 'admin'},
            ProjectionExpression='tenant_id, nombre_empresa'
        )

        items = result.get('Items', [])

        # Filtrar solo los campos necesarios y eliminar duplicados por tenant_id
        empresas = []
        tenant_ids_vistos = set()
        for item in items:
            tid = item.get('tenant_id')
            if tid and tid not in tenant_ids_vistos:
                tenant_ids_vistos.add(tid)
                empresas.append({
                    'tenant_id': tid,
                    'nombre_empresa': item.get('nombre_empresa', tid)
                })

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'total': len(empresas),
                'data': empresas
            })
        }

    except Exception as e:
        print(f"[ERROR] obtener_empresas: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'message': str(e)
            })
        }
