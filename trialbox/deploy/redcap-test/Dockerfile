# The web server of our own REDCap test instance (NEW-EDC-0, D-584). PHP with Apache and the two extensions REDCap
# needs for an install and its API (mysqli, gd is not needed for the API). REDCap's code is mounted, never copied.
# NEVER BUILT in this repository's history: the instance needs the owner's zip.
FROM php:8.2-apache
RUN docker-php-ext-install mysqli \
 && printf 'max_input_vars=100000\nupload_max_filesize=64M\npost_max_size=64M\nmemory_limit=512M\n' \
    > /usr/local/etc/php/conf.d/redcap.ini \
 && mkdir -p /var/redcap-temp && chown www-data:www-data /var/redcap-temp
