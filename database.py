import os
import mysql.connector


def obtener_conexion():

    conexion = mysql.connector.connect(
        host=os.environ.get(
            "DB_HOST",
            "localhost"
        ),

        port=int(
            os.environ.get(
                "DB_PORT",
                "3306"
            )
        ),

        user=os.environ.get(
            "DB_USER",
            "root"
        ),

        password=os.environ.get(
            "DB_PASSWORD",
            ""
        ),

        database=os.environ.get(
            "DB_NAME",
            "ABC"
        ),

        connection_timeout=10
    )

    return conexion


if __name__ == "__main__":

    try:

        conexion = obtener_conexion()

        print(
            "✅ Conexión a MySQL exitosa"
        )

        conexion.close()

    except Exception as e:

        print(
            "❌ Error de conexión:"
        )

        print(e)