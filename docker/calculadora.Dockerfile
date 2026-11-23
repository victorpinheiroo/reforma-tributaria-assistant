# The Federal Revenue's official calculator, pinned, built from its public source (MIT).
# Built with the official Maven image: the GitHub source archive of the tag does not ship the
# Maven Wrapper jar, so ./mvnw cannot run from it.
FROM maven:3.9-eclipse-temurin-25 AS build
ARG VERSION=1.7.2
WORKDIR /src
ADD https://github.com/ReceitaFederal/calculadora-rtc-regime-regular/archive/refs/tags/${VERSION}.tar.gz /tmp/calc.tgz
RUN tar xzf /tmp/calc.tgz --strip-components=1 \
 && mkdir -p calculadora/db \
 && mvn -q --batch-mode flyway:migrate -Dflyway.configFiles=./flyway/flyway-pro.conf \
 && mvn -q --batch-mode clean package -DskipTests

FROM eclipse-temurin:25-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /calc
COPY --from=build /src/target/api-regime-geral.jar ./api-regime-geral.jar
COPY --from=build /src/calculadora/db ./calculadora/db
EXPOSE 8080
CMD ["java", "-Dspring.profiles.active=offline", "-jar", "api-regime-geral.jar"]
