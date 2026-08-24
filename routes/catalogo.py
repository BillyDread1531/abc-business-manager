from flask import Blueprint, render_template, request
from database import obtener_conexion


catalogo_bp = Blueprint(
    "catalogo",
    __name__,
    url_prefix="/catalogo"
)


@catalogo_bp.route("/")
def index():

    busqueda = request.args.get(
        "q",
        ""
    ).strip()

    categoria_id = request.args.get(
        "categoria_id",
        ""
    ).strip()

    tipo_precio = request.args.get(
        "tipo_precio",
        ""
    ).strip()

    conexion = obtener_conexion()
    cursor = conexion.cursor(
        dictionary=True
    )

    cursor.execute("""
        SELECT
            id,
            nombre
        FROM categorias
        WHERE activo = 1
        ORDER BY nombre ASC
    """)

    categorias = cursor.fetchall()

    condiciones = [
        "p.activo = 1",
        "p.vendible = 1"
    ]

    parametros = []

    if busqueda:

        condiciones.append("""
            (
                p.nombre LIKE %s
                OR p.descripcion LIKE %s
                OR c.nombre LIKE %s
            )
        """)

        texto_busqueda = f"%{busqueda}%"

        parametros.extend([
            texto_busqueda,
            texto_busqueda,
            texto_busqueda
        ])

    if categoria_id:

        condiciones.append(
            "p.categoria_id = %s"
        )

        parametros.append(
            categoria_id
        )

    if tipo_precio:

        condiciones.append(
            "p.tipo_calculo_precio = %s"
        )

        parametros.append(
            tipo_precio
        )

    where_sql = (
        "WHERE "
        + " AND ".join(condiciones)
    )

    cursor.execute(
        f"""
        SELECT
            p.id,
            p.nombre,
            p.descripcion,
            p.tipo,
            p.metodo_produccion,
            p.precio_base,
            p.tipo_calculo_precio,
            p.unidad_calculo_area,
            p.controla_stock,
            p.stock_actual,

            c.id AS categoria_id,
            c.nombre AS categoria

        FROM productos p

        INNER JOIN categorias c
            ON c.id = p.categoria_id

        {where_sql}

        ORDER BY
            c.nombre ASC,
            p.nombre ASC
        """,
        tuple(parametros)
    )

    productos = cursor.fetchall()

    for producto in productos:

        cursor.execute("""
            SELECT
                id,
                cantidad_minima,
                cantidad_maxima,
                precio_unitario
            FROM precios_producto
            WHERE producto_id = %s
            AND activo = 1
            ORDER BY cantidad_minima ASC
        """, (
            producto["id"],
        ))

        producto["precios"] = cursor.fetchall()

        cursor.execute("""
            SELECT
                id,
                sku,
                nombre,
                talla,
                color,
                precio,
                costo_base
            FROM variantes_producto
            WHERE producto_id = %s
            AND activo = 1
            ORDER BY
                nombre ASC,
                talla ASC,
                color ASC
        """, (
            producto["id"],
        ))

        producto["variantes"] = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS total,

            SUM(
                CASE
                    WHEN tipo_calculo_precio = 'FIJO'
                    THEN 1 ELSE 0
                END
            ) AS fijos,

            SUM(
                CASE
                    WHEN tipo_calculo_precio = 'M2'
                    THEN 1 ELSE 0
                END
            ) AS areas,

            SUM(
                CASE
                    WHEN tipo_calculo_precio = 'METRO_LINEAL'
                    THEN 1 ELSE 0
                END
            ) AS metros,

            SUM(
                CASE
                    WHEN tipo_calculo_precio = 'MANUAL'
                    THEN 1 ELSE 0
                END
            ) AS manuales

        FROM productos
        WHERE activo = 1
          AND vendible = 1
    """)

    contadores = cursor.fetchone()

    cursor.close()
    conexion.close()

    return render_template(
        "catalogo/index.html",

        productos=productos,
        categorias=categorias,

        busqueda=busqueda,
        categoria_id=categoria_id,
        tipo_precio=tipo_precio,

        contadores=contadores
    )