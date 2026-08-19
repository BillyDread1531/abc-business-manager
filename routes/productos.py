from flask import Blueprint, render_template, request, redirect, url_for
from database import obtener_conexion

productos_bp = Blueprint(
    "productos",
    __name__,
    url_prefix="/productos"
)


@productos_bp.route("/")
def listar():

    busqueda = request.args.get("q", "").strip()

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if busqueda:
        cursor.execute("""
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
                c.nombre AS categoria
            FROM productos p
            INNER JOIN categorias c
                ON p.categoria_id = c.id
            WHERE p.activo = 1
            AND (
                p.nombre LIKE %s
                OR c.nombre LIKE %s
            )
            ORDER BY p.nombre ASC
        """, (
            f"%{busqueda}%",
            f"%{busqueda}%"
        ))
    else:
        cursor.execute("""
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
                c.nombre AS categoria
            FROM productos p
            INNER JOIN categorias c
                ON p.categoria_id = c.id
            WHERE p.activo = 1
            ORDER BY p.nombre ASC
        """)

    productos = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "productos/lista.html",
        productos=productos,
        busqueda=busqueda
    )

@productos_bp.route("/nuevo", methods=["GET", "POST"])
def nuevo():

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    if request.method == "POST":

        nombre = request.form["nombre"].strip()

        if nombre:
            nombre = nombre[:1].upper() + nombre[1:]

        descripcion = request.form.get(
            "descripcion",
            ""
        ).strip()

        categoria_id = request.form["categoria_id"]

        tipo = request.form.get(
            "tipo",
            "PRODUCTO"
        )

        metodo_produccion = request.form.get(
            "metodo_produccion",
            "INTERNA"
        )

        precio_base = request.form.get(
            "precio_base"
        ) or 0

        tipo_calculo_precio = request.form.get(
            "tipo_calculo_precio",
            "FIJO"
        )

        tipos_calculo_validos = {
            "FIJO",
            "M2",
            "METRO_LINEAL",
            "MANUAL"
        }

        if tipo_calculo_precio not in tipos_calculo_validos:
            tipo_calculo_precio = "FIJO"

        unidad_calculo_area = request.form.get(
            "unidad_calculo_area",
            "M2"
        ).strip().upper()

        if unidad_calculo_area not in {"CM2", "M2"}:
            unidad_calculo_area = "M2"

        # Solo tiene efecto para productos calculados por área.
        if tipo_calculo_precio != "M2":
            unidad_calculo_area = "M2"

        unidad_calculo_area = request.form.get(
            "unidad_calculo_area",
            "M2"
        ).strip().upper()

        if unidad_calculo_area not in {"CM2", "M2"}:
            unidad_calculo_area = "M2"

        # Solo tiene efecto para productos calculados por área.
        if tipo_calculo_precio != "M2":
            unidad_calculo_area = "M2"

        controla_stock = (
            1
            if request.form.get("controla_stock")
            else 0
        )

        # ========================================================
        # SERVICIOS
        # ========================================================

        if tipo == "SERVICIO":

            # La columna metodo_produccion es NOT NULL.
            metodo_produccion = "INTERNA"

            controla_stock = 0

        # ========================================================
        # STOCK
        # ========================================================

        if controla_stock:

            stock_actual = (
                request.form.get("stock_inicial")
                or 0
            )

            stock_minimo = (
                request.form.get("stock_minimo")
                or 0
            )

        else:

            stock_actual = 0
            stock_minimo = 0

        cursor.execute("""
            INSERT INTO productos
            (
                categoria_id,
                nombre,
                descripcion,
                tipo,
                metodo_produccion,
                precio_base,
                tipo_calculo_precio,
                unidad_calculo_area,
                controla_stock,
                stock_actual,
                stock_minimo
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """, (
            categoria_id,
            nombre,
            descripcion or None,
            tipo,
            metodo_produccion,
            precio_base,
            tipo_calculo_precio,
            unidad_calculo_area,
            controla_stock,
            stock_actual,
            stock_minimo
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for("productos.listar")
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

    cursor.close()
    conexion.close()

    return render_template(
        "productos/nuevo.html",
        categorias=categorias
    )


@productos_bp.route("/<int:producto_id>/precios")
def precios(producto_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nombre, precio_base, tipo_calculo_precio, unidad_calculo_area
        FROM productos
        WHERE id = %s
    """, (producto_id,))

    producto = cursor.fetchone()

    cursor.execute("""
        SELECT
            id,
            cantidad_minima,
            cantidad_maxima,
            precio_unitario,
            activo
        FROM precios_producto
        WHERE producto_id = %s
        AND activo = 1
        ORDER BY cantidad_minima ASC
    """, (producto_id,))

    precios = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template(
        "productos/precios.html",
        producto=producto,
        precios=precios
    )

@productos_bp.route("/<int:producto_id>/precios/nuevo", methods=["GET", "POST"])
def nuevo_precio(producto_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, nombre
        FROM productos
        WHERE id = %s
        AND activo = 1
    """, (producto_id,))

    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conexion.close()
        return "Producto no encontrado", 404

    if request.method == "POST":

        cantidad_minima = request.form["cantidad_minima"]
        cantidad_maxima = request.form.get("cantidad_maxima") or None
        precio_unitario = request.form["precio_unitario"]

        cantidad_minima_num = float(cantidad_minima)
        cantidad_maxima_num = (
            float(cantidad_maxima)
            if cantidad_maxima
            else None
        )

        precio_num = float(precio_unitario)

        error = None

        if cantidad_minima_num <= 0:
            error = "La cantidad mínima debe ser mayor que 0."

        elif cantidad_maxima_num is not None:
            if cantidad_maxima_num < cantidad_minima_num:
                error = "La cantidad máxima no puede ser menor que la mínima."

        if precio_num < 0:
            error = "El precio no puede ser negativo."

        # Comprobar que el nuevo rango no se cruce
        # con otro rango existente
        if error is None:

            cursor.execute("""
                SELECT id
                FROM precios_producto
                WHERE producto_id = %s
                AND activo = 1
                AND cantidad_minima <= %s
                AND (
                    cantidad_maxima IS NULL
                    OR %s IS NULL
                    OR cantidad_maxima >= %s
                )
                LIMIT 1
            """, (
                producto_id,
                cantidad_maxima_num if cantidad_maxima_num is not None
                else cantidad_minima_num,

                cantidad_minima_num,

                cantidad_minima_num
            ))

            rango_existente = cursor.fetchone()

            if rango_existente:
                error = (
                    "El rango de cantidades se cruza "
                    "con otro precio existente."
                )

        if error:

            cursor.close()
            conexion.close()

            return render_template(
                "productos/nuevo.html",
                producto=producto,
                error=error
            )

        cursor.execute("""
            INSERT INTO precios_producto
            (
                producto_id,
                cantidad_minima,
                cantidad_maxima,
                precio_unitario
            )
            VALUES (%s, %s, %s, %s)
        """, (
            producto_id,
            cantidad_minima,
            cantidad_maxima,
            precio_unitario
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for(
                "productos.precios",
                producto_id=producto_id
            )
        )

    cursor.close()
    conexion.close()

    return render_template(
        "productos/nuevo.html",
        producto=producto
    )

@productos_bp.route("/<int:producto_id>/editar", methods=["GET", "POST"])
def editar(producto_id):

    conexion = obtener_conexion()
    cursor = conexion.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            id,
            categoria_id,
            nombre,
            descripcion,
            tipo,
            metodo_produccion,
            precio_base,
            tipo_calculo_precio,
            unidad_calculo_area,
            controla_stock,
            stock_actual,
            stock_minimo
        FROM productos
        WHERE id = %s
    """, (producto_id,))

    producto = cursor.fetchone()

    if not producto:
        cursor.close()
        conexion.close()
        return "Producto no encontrado", 404

    if request.method == "POST":

        nombre = request.form["nombre"].strip()

        if nombre:
            nombre = nombre[:1].upper() + nombre[1:]

        descripcion = request.form.get(
            "descripcion",
            ""
        ).strip()

        categoria_id = request.form["categoria_id"]

        tipo = request.form.get(
            "tipo",
            "PRODUCTO"
        )

        metodo_produccion = request.form.get(
            "metodo_produccion",
            "INTERNA"
        )

        precio_base = request.form.get(
            "precio_base"
        ) or 0

        tipo_calculo_precio = request.form.get(
            "tipo_calculo_precio",
            "FIJO"
        )

        tipos_calculo_validos = {
            "FIJO",
            "M2",
            "METRO_LINEAL",
            "MANUAL"
        }

        if tipo_calculo_precio not in tipos_calculo_validos:
            tipo_calculo_precio = "FIJO"

        unidad_calculo_area = request.form.get(
            "unidad_calculo_area",
            "M2"
        ).strip().upper()

        if unidad_calculo_area not in {"CM2", "M2"}:
            unidad_calculo_area = "M2"

        if tipo_calculo_precio != "M2":
            unidad_calculo_area = "M2"

        controla_stock = (
            1
            if request.form.get("controla_stock")
            else 0
        )

        if tipo == "SERVICIO":
            metodo_produccion = "INTERNA"
            controla_stock = 0

        if controla_stock:
            stock_minimo = (
                request.form.get("stock_minimo")
                or 0
            )
        else:
            stock_minimo = 0

        cursor.execute("""
            UPDATE productos
            SET
                categoria_id = %s,
                nombre = %s,
                descripcion = %s,
                tipo = %s,
                metodo_produccion = %s,
                precio_base = %s,
                tipo_calculo_precio = %s,
                unidad_calculo_area = %s,
                controla_stock = %s,
                stock_minimo = %s
            WHERE id = %s
        """, (
            categoria_id,
            nombre,
            descripcion or None,
            tipo,
            metodo_produccion,
            precio_base,
            tipo_calculo_precio,
            unidad_calculo_area,
            controla_stock,
            stock_minimo,
            producto_id
        ))

        conexion.commit()

        cursor.close()
        conexion.close()

        return redirect(
            url_for("productos.listar")
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

    cursor.close()
    conexion.close()

    return render_template(
        "productos/editar.html",
        producto=producto,
        categorias=categorias
    )