import boto3
import json
import hashlib
import os

dynamodb = boto3.resource('dynamodb')
TABLE_USUARIOS = os.environ.get('DYNAMODB_USUARIOS_TABLE', 't_usuarios')


def lambda_handler(event, context):
    """
    Crea un usuario en t_usuarios.

    Roles soportados:
      - 'admin'    → Dueño de la PYME. Debe incluir nombre_empresa.
                     Su tenant_id es el ID único de su empresa.
      - 'empleado' → Especialista registrado por el admin.
                     Tiene un area asignada (ej: "Ventas").

    Body requerido:
        tenant_id     - ID de la empresa (lo elige el admin en su registro)
        correo        - Email del usuario (SK en DynamoDB)
        password      - Contraseña en texto plano (se guarda como hash SHA-256)
        rol           - "admin" | "empleado"
        area          - Área del empleado (requerido si rol == 'empleado')
        nombre_empresa- Nombre visible de la empresa (requerido si rol == 'admin')
    """
    try:
        body = event.get('body', {})
        if isinstance(body, str):
            body = json.loads(body)
        if not isinstance(body, dict):
            body = {}

        tenant_id = body.get('tenant_id', '').strip()
        correo = body.get('correo', '').strip()
        password = body.get('password', '')
        rol = body.get('rol', 'empleado').strip().lower()
        area = body.get('area', '').strip()
        nombre_empresa = body.get('nombre_empresa', '').strip()

        # ── Validaciones ──────────────────────────────────────────────────
        if not all([tenant_id, correo, password, rol]):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Campos requeridos: tenant_id, correo, password, rol'
                })
            }

        if rol not in ('admin', 'empleado'):
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El rol debe ser "admin" o "empleado"'
                })
            }

        if rol == 'admin' and not nombre_empresa:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El rol "admin" requiere el campo nombre_empresa'
                })
            }

        if rol == 'empleado' and not area:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'El rol "empleado" requiere el campo area'
                })
            }

        # ── Hash de contraseña ────────────────────────────────────────────
        password_hash = hashlib.sha256(password.encode('utf-8')).hexdigest()

        tabla = dynamodb.Table(TABLE_USUARIOS)

        # Verificar si el usuario ya existe (mismo tenant_id + correo)
        existing = tabla.get_item(
            Key={'tenant_id': tenant_id, 'correo': correo}
        )
        if 'Item' in existing:
            return {
                'statusCode': 409,
                'body': json.dumps({
                    'status': 'error',
                    'message': 'Ya existe un usuario con ese correo en este tenant'
                })
            }

        # ── Construir item según rol ───────────────────────────────────────
        item = {
            'tenant_id': tenant_id,
            'correo': correo,
            'password_hash': password_hash,
            'rol': rol,
        }

        if rol == 'admin':
            item['nombre_empresa'] = nombre_empresa
            item['area'] = ''  # Los admins no tienen área fija
            # El admin tiene un catálogo de áreas de su empresa
            item['areas'] = body.get('areas', []) 
        else:
            item['area'] = area
            item['nombre_empresa'] = ''

        # ── Guardar en DynamoDB ───────────────────────────────────────────
        tabla.put_item(Item=item)

        # Respuesta sin exponer datos sensibles
        return {
            'statusCode': 201,
            'body': json.dumps({
                'status': 'success',
                'message': f'Usuario con rol "{rol}" creado exitosamente',
                'data': {
                    'tenant_id': tenant_id,
                    'correo': correo,
                    'rol': rol,
                    'area': item.get('area'),
                    'areas': item.get('areas', []),
                    'nombre_empresa': item.get('nombre_empresa')
                }
            })
        }

    except json.JSONDecodeError as e:
        print(f"[ERROR] crear_usuario - JSON inválido: {e}")
        return {
            'statusCode': 400,
            'body': json.dumps({'status': 'error', 'message': 'Body inválido, se esperaba JSON'})
        }
    except Exception as e:
        print(f"[ERROR] crear_usuario: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'status': 'error', 'message': str(e)})
        }
